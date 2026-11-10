"""Run the isolated-network cases (kubernetes-isolated-cases.md) on kind.

The cluster is the disposable `keeplane-isolated` kind cluster the isolated
network job of the Kubernetes live checks workflow creates: Calico enforces
NetworkPolicy, ingress-nginx
publishes Keeplane on https://keeplane.isolated.test, the model provider
fixture runs on the runner outside the cluster, and an internal registry on
the same network holds every image the install uses and the node pulls
through it. The cases close the network's outside access and outside name
lookups themselves (ISO-02), restart every Keeplane pod and then the node,
clear the node's images and start it again from the internal registry
(ISO-11), and run the admin journey with only the model provider reachable.

They refuse any kubeconfig context other than kind-keeplane-isolated, and
change the runner's firewall, so they run only in that workflow.
"""

import http.cookiejar
import importlib.util
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import (
    HTTPCookieProcessor,
    HTTPSHandler,
    Request,
    build_opener,
    urlopen,
)

import pytest

from tests.support.protected_preview import BrowserCsrfHandler

ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = os.environ.get(
    "KEEPLANE_ISOLATED_KUBECONFIG", "/tmp/keeplane-isolated-kubeconfig"
)
RUNTIME = Path(
    os.environ.get("KEEPLANE_ISOLATED_RUNTIME", "/tmp/keeplane-isolated-runtime")
)
CONTEXT = "kind-keeplane-isolated"
NODE = "keeplane-isolated-control-plane"
HOST = "keeplane.isolated.test"
BASE = "https://" + HOST
# The model provider fixture on the runner: the network's one outside place.
PROVIDER = "172.30.0.1"
PROVIDER_PORT = 18082
PYTHON_IMAGE = (
    "python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a"
)
CLOSE = ROOT / "tests/fixtures/isolated-network/close-network.sh"
# The internal registry (tests/fixtures/isolated-network/mirror.py): its
# container, its address on the isolated network, the images the workflow
# copied into it and the images the node image itself held before the install.
_spec = importlib.util.spec_from_file_location(
    "isolated_mirror", ROOT / "tests/fixtures/isolated-network/mirror.py"
)
MIRROR_TOOL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MIRROR_TOOL)
MIRROR = MIRROR_TOOL.MIRROR
MIRROR_CONTAINER = "keeplane-mirror"
MIRRORED = RUNTIME / "mirror-images.json"
NODE_IMAGE_IMAGES = RUNTIME / "node-image-images.json"
APP_IMAGE = os.environ.get("KEEPLANE_ISOLATED_APP_IMAGE", "")
# An image the node never had, for the registry pull check, and a pull
# straight from its registry: ctr reads no hosts.toml unless told to.
ABSENT_IMAGE = "registry.k8s.io/e2e-test-images/agnhost:2.53"
OUTSIDE_PULL = ("ctr", "-n", "k8s.io", "images", "pull")

# Runs in a pod: try each target and report "open", "open:<HTTP status>" or
# "blocked:<error>", unwrapping urllib's URLError to the socket error under it
# and naming a plain OSError by its errno. A dropped connection times out.
PROBE = """import errno,json,socket,sys,urllib.error,urllib.request
out={}
for t in json.loads(sys.argv[1]):
 try:
  if t.get("path"):
   with urllib.request.urlopen("http://%s:%d%s"%(t["host"],t["port"],t["path"]),timeout=5) as r:
    out[t["name"]]="open:%d"%r.status
  else:
   socket.create_connection((t["host"],t["port"]),timeout=5).close()
   out[t["name"]]="open"
 except urllib.error.HTTPError as e:
  out[t["name"]]="open:%d"%e.code
 except Exception as e:
  if isinstance(e,urllib.error.URLError) and isinstance(e.reason,BaseException):
   e=e.reason
  n=type(e).__name__
  if n=="OSError" and e.errno:
   n+=":"+errno.errorcode.get(e.errno,str(e.errno))
  out[t["name"]]="blocked:"+n
print(json.dumps(out))"""

# Runs in a pod: look each name up as the pod's own resolver does (through
# CoreDNS) and report "resolved:<address>" or "failed:<error>".
LOOKUP = """import json,socket,sys
out={}
for n in json.loads(sys.argv[1]):
 try:
  out[n]="resolved:"+socket.getaddrinfo(n,443,socket.AF_INET,socket.SOCK_STREAM)[0][4][0]
 except OSError as e:
  out[n]="failed:"+type(e).__name__+":"+str(e.args[0] if e.args else "")
print(json.dumps(out))"""

# Runs in the visitor pod: open the web UI through the ingress controller's
# Service with the run's CA, as a browser inside the network would, following
# the app's redirects on the same host (to its sign-in page).
INSIDE_UI = """import socket,ssl
c=ssl.create_default_context(cafile="/ca/ca.crt")
path="/"
for hop in range(5):
 s=c.wrap_socket(socket.create_connection(("ingress-nginx-controller.ingress-nginx.svc.cluster.local",443),timeout=10),server_hostname="keeplane.isolated.test")
 s.sendall(("GET %s HTTP/1.1\\r\\nHost: keeplane.isolated.test\\r\\nConnection: close\\r\\n\\r\\n"%path).encode())
 d=b""
 while True:
  b=s.recv(65536)
  if not b:
   break
  d+=b
 head=d.split(b"\\r\\n\\r\\n",1)[0].decode(errors="replace").split("\\r\\n")
 location=[h.split(":",1)[1].strip() for h in head[1:] if h.lower().startswith("location:")]
 if not head[0].split()[1].startswith("3") or not location:
  break
 path=location[0].replace("https://keeplane.isolated.test","",1)
 if not path.startswith("/"):
  break
print(head[0], path, b'id="root"' in d)"""

# What a NetworkPolicy or a closed firewall does to a connection: drop it (a
# timeout), reset or refuse it, or answer "administratively prohibited"
# (EHOSTUNREACH). A failed name lookup or any other error is not a block.
BLOCKED_BY = {
    "TimeoutError",
    "timeout",
    "ConnectionResetError",
    "ConnectionRefusedError",
    "OSError:EHOSTUNREACH",
}

MODEL = {"name": "model", "host": PROVIDER, "port": PROVIDER_PORT, "path": "/health"}
# Outside places by IP address, so a probe never depends on a name lookup.
INTERNET = {"name": "internet", "host": "1.1.1.1", "port": 443}
REGISTRY_HOST = "registry.k8s.io"
# In-cluster names CoreDNS answers itself, which must keep working.
INSIDE_NAME = "service.inside.svc.cluster.local"
APP_NAME = "keeplane-app.keeplane.svc.cluster.local"
INSIDE = {
    "name": "inside_service",
    "host": "service.inside.svc.cluster.local",
    "port": 8080,
    "path": "/",
}
APP = {
    "name": "app",
    "host": "keeplane-app.keeplane.svc.cluster.local",
    "port": 3000,
    "path": "/health",
}
GATEWAY = {
    "name": "gateway",
    "host": "keeplane.keeplane.svc.cluster.local",
    "port": 4000,
}
IN_CLUSTER_MODEL = {
    "name": "in_cluster_model",
    "host": "model.keeplane.svc.cluster.local",
    "port": 18080,
    "path": "/health",
}


def registry_target():
    """The registry by an IPv4 address the runner resolves for it."""
    address = socket.getaddrinfo(
        REGISTRY_HOST, 443, socket.AF_INET, socket.SOCK_STREAM
    )[0][4][0]
    return {"name": "registry", "host": address, "port": 443}


def run(*command, timeout=300, check=True):
    result = subprocess.run(
        command, check=False, cwd=ROOT, text=True, capture_output=True, timeout=timeout
    )
    if check and result.returncode:
        raise RuntimeError(f"{' '.join(command[:4])} failed: {result.stderr[-400:]}")
    return result


def kubectl(*args, timeout=300):
    return run("kubectl", "--kubeconfig", KUBECONFIG, *args, timeout=timeout).stdout


POD_EXEC = {
    "app": ("-n", "keeplane", "exec", "deploy/keeplane-app", "-c", "app"),
    "model": ("-n", "keeplane", "exec", "deploy/model"),
    "visitor": ("-n", "inside", "exec", "visitor"),
    # The protected release's app (test_kubernetes_isolated_protected.py).
    "protected_app": (
        "-n",
        "keeplane-protected",
        "exec",
        "deploy/keeplane-app",
        "-c",
        "app",
    ),
}


def probe(where, targets):
    """Probe from a pod: ("app" | "model" | "visitor" | "protected_app")."""
    output = kubectl(*POD_EXEC[where], "--", "python", "-c", PROBE, json.dumps(targets))
    return json.loads(output)


def lookup(where, names):
    """Look names up from a pod, or from the node itself ("node")."""
    if where != "node":
        output = kubectl(
            *POD_EXEC[where], "--", "python", "-c", LOOKUP, json.dumps(names)
        )
        return json.loads(output)
    out = {}
    for name in names:
        result = run(
            "docker", "exec", NODE, "getent", "ahostsv4", name, check=False, timeout=60
        )
        found = result.stdout.split()
        out[name] = (
            "resolved:" + found[0]
            if result.returncode == 0 and found
            else f"failed:exit {result.returncode}"
        )
    return out


def resolved(observed, *names):
    return all(observed.get(name, "").startswith("resolved:") for name in names)


def unresolved(observed, *names):
    return all(observed.get(name, "").startswith("failed:") for name in names)


GATEWAY_PROBES = [0]


def probe_gateway(targets, namespace="keeplane"):
    """Probe from inside gateway copy 0's network with an ephemeral container.

    The gateway image has no shell or Python, so a pinned Python container
    joins the Pod; the Pod's NetworkPolicy applies to it as to the gateway,
    and to the model enroller beside it in the protected release's copies.
    """
    GATEWAY_PROBES[0] += 1
    name = f"probe-{int(time.time())}-{GATEWAY_PROBES[0]}"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as custom:
        json.dump(
            {"securityContext": {"runAsUser": 65532, "runAsGroup": 65532}}, custom
        )
    try:
        kubectl(
            "-n",
            namespace,
            "debug",
            "pod/keeplane-gateway-0",
            "--image=" + PYTHON_IMAGE,
            "--image-pull-policy=IfNotPresent",
            "--container=" + name,
            "--profile=restricted",
            "--custom=" + custom.name,
            "--",
            "python",
            "-c",
            PROBE,
            json.dumps(targets),
        )
    finally:
        os.unlink(custom.name)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        pod = json.loads(
            kubectl("-n", namespace, "get", "pod", "keeplane-gateway-0", "-o", "json")
        )
        for status in pod["status"].get("ephemeralContainerStatuses", []):
            if status["name"] == name and "terminated" in status.get("state", {}):
                logs = kubectl(
                    "-n", namespace, "logs", "pod/keeplane-gateway-0", "-c", name
                )
                return json.loads(logs.strip().splitlines()[-1])
        time.sleep(2)
    raise RuntimeError("The gateway probe did not finish")


def blocked(observed, *names):
    """Every named target was blocked by the network, not by a lookup or bug."""
    return all(
        observed.get(name, "").startswith("blocked:")
        and observed[name].split(":", 1)[1] in BLOCKED_BY
        for name in names
    )


def tls_context():
    return ssl.create_default_context(cafile=str(RUNTIME / "ca.crt"))


def fetch(path, attempts=1):
    """Fetch a page through the ingress, retrying while it starts."""
    opener = build_opener(HTTPSHandler(context=tls_context()))
    for attempt in range(attempts):
        try:
            with opener.open(Request(BASE + path), timeout=15) as response:
                return response.status, response.read()
        except HTTPError as error:
            if attempt == attempts - 1:
                return error.code, error.read()
        except OSError:
            if attempt == attempts - 1:
                raise
        time.sleep(3)


def sign_in():
    opener = build_opener(
        HTTPSHandler(context=tls_context()),
        BrowserCsrfHandler(BASE),
        HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )
    opener.addheaders = [("X-Keeplane-Action", "1")]
    password = (RUNTIME / "first-admin-password").read_text().strip()
    status, _ = api(
        opener, "/api/session", {"username": "first-admin", "password": password}
    )
    if status != 200:
        raise RuntimeError(f"Admin sign-in failed with {status}")
    return opener


def api(opener, path, body=None, method=None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with opener.open(request, timeout=120) as response:
            return response.status, json.loads(response.read() or b"{}")
    except HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, {"raw": raw[:200].decode(errors="replace")}


def provider_calls():
    with urlopen(f"http://127.0.0.1:{PROVIDER_PORT}/calls", timeout=10) as response:
        return json.load(response)["count"]


def node_reaches_registry():
    result = run(
        "docker",
        "exec",
        NODE,
        "curl",
        "-sS",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "-m",
        "10",
        "https://registry.k8s.io/v2/",
        check=False,
        timeout=60,
    )
    return result.returncode == 0 and result.stdout not in ("", "000"), result.stdout


def pods(namespace, selector=None):
    args = ["-n", namespace, "get", "pods", "-o", "json"]
    if selector:
        args += ["-l", selector]
    return [
        pod
        for pod in json.loads(kubectl(*args))["items"]
        if pod["status"].get("phase") != "Succeeded"
        and not pod["metadata"].get("deletionTimestamp")
    ]


def ready(pod):
    return pod["status"].get("phase") == "Running" and any(
        c["type"] == "Ready" and c["status"] == "True"
        for c in pod["status"].get("conditions", [])
    )


def mirror_key(ref):
    """(registry, path, digest) of a pinned image, or None if not pinned."""
    try:
        registry, path, _, digest = MIRROR_TOOL.split(ref)
    except SystemExit:
        return None
    return registry, path, digest


def node_image():
    """The names and IDs of the images the node image held before the install."""
    images = json.loads(NODE_IMAGE_IMAGES.read_text())["images"]
    names = {
        name
        for image in images
        for name in image.get("repoTags", []) + image.get("repoDigests", [])
    }
    return names, {image["id"] for image in images}


def installed_images(ephemeral=True):
    """Every image a pod names that the node image did not already hold."""
    names, _ = node_image()
    found = set()
    for pod in json.loads(kubectl("get", "pods", "-A", "-o", "json"))["items"]:
        spec = pod["spec"]
        containers = spec.get("initContainers", []) + spec["containers"]
        if ephemeral:
            containers += spec.get("ephemeralContainers", [])
        found |= {c["image"] for c in containers if c["image"] not in names}
    return found


def node_manifest(path, digest):
    """Ask the internal registry from the node for a manifest by digest."""
    result = run(
        "docker",
        "exec",
        NODE,
        "curl",
        "-sS",
        "-I",
        "-m",
        "10",
        "-H",
        "Accept: " + MIRROR_TOOL.ACCEPT,
        f"http://{MIRROR}/v2/{path}/manifests/{digest}",
        check=False,
        timeout=60,
    )
    lines = result.stdout.splitlines()
    status = lines[0].split()[1] if lines and len(lines[0].split()) > 1 else "none"
    served = next(
        (
            line.split(":", 1)[1].strip()
            for line in lines
            if line.lower().startswith("docker-content-digest:")
        ),
        None,
    )
    return served if status == "200" else f"status {status}"


# One request in the internal registry's access log (Combined Log Format).
ACCESS = re.compile(r'^(\S+) \S+ \S+ \[[^\]]+\] "(GET|HEAD) (\S+) HTTP/[\d.]+" (\d{3})')


def mirror_requests(since):
    """(client, path without query, status) of each request since a time."""
    logs = run("docker", "logs", "--since", since, MIRROR_CONTAINER, timeout=60)
    requests = []
    for line in (logs.stdout + "\n" + logs.stderr).splitlines():
        match = ACCESS.match(line.strip())
        if match:
            client, _, path, status = match.groups()
            requests.append((client, path.split("?", 1)[0], status))
    return requests


def node_address():
    return run(
        "docker",
        "inspect",
        "-f",
        '{{(index .NetworkSettings.Networks "kind").IPAddress}}',
        NODE,
    ).stdout.strip()


def wait_for_node():
    """Wait for the restarted node and its network plugin to be ready."""
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        nodes = run(
            "kubectl",
            "--kubeconfig",
            KUBECONFIG,
            "get",
            "nodes",
            "-o",
            "json",
            check=False,
            timeout=30,
        )
        if nodes.returncode == 0 and all(
            any(
                c["type"] == "Ready" and c["status"] == "True"
                for c in n["status"]["conditions"]
            )
            for n in json.loads(nodes.stdout)["items"]
        ):
            break
        time.sleep(5)
    else:
        raise RuntimeError("The node did not come back Ready")
    for namespace, workload in (
        ("kube-system", "daemonset/calico-node"),
        ("kube-system", "deployment/calico-kube-controllers"),
        ("kube-system", "deployment/coredns"),
    ):
        kubectl(
            "-n",
            namespace,
            "rollout",
            "status",
            workload,
            "--timeout=300s",
            timeout=400,
        )


def wait_for_restarted_pods(since, namespaces, until=lambda: True):
    """Wait until every pod in the namespaces runs containers started after
    `since` (an RFC 3339 UTC time) and is ready, and `until()` holds.

    Right after a node restart the API still reports the pods' old status,
    so a rollout status alone can pass before the node has restarted them.
    """
    deadline = time.monotonic() + 600
    while True:
        try:
            found = [p for namespace in namespaces for p in pods(namespace)]
            fresh = {
                p["metadata"]["name"]: ready(p)
                and all(
                    c.get("state", {}).get("running", {}).get("startedAt", "") >= since
                    for c in p["status"].get("containerStatuses", [{}])
                )
                for p in found
            }
            done = found and all(fresh.values()) and until()
        except RuntimeError as error:
            fresh, done = {"error": str(error)[:200]}, False
        if done or time.monotonic() > deadline:
            return fresh
        time.sleep(10)


# The protected release (ISO-13 to ISO-20) restarts with the node too.
RESTARTED = (
    "keeplane",
    "keeplane-protected",
    "inside",
    "ingress-nginx",
    "kube-system",
)


def wait_for_workloads(timeout="300s"):
    for kind_name in (
        "deployment/keeplane-app",
        "statefulset/keeplane-gateway",
        "deployment/model",
        "deployment/postgres",
    ):
        kubectl(
            "-n",
            "keeplane",
            "rollout",
            "status",
            kind_name,
            "--timeout=" + timeout,
            timeout=400,
        )
    kubectl(
        "-n",
        "ingress-nginx",
        "rollout",
        "status",
        "deployment/ingress-nginx-controller",
        "--timeout=" + timeout,
        timeout=400,
    )
    kubectl(
        "-n",
        "inside",
        "wait",
        "--for=condition=Ready",
        "pod",
        "--all",
        "--timeout=" + timeout,
        timeout=400,
    )


def ask(opener, model, prompt="Say hello"):
    return api(opener, "/api/ask", {"model": model, "prompt": prompt})


def run_cases():
    context = kubectl("config", "current-context").strip()
    if context != CONTEXT:
        raise SystemExit(f"Refusing Kubernetes context {context!r}; expected {CONTEXT}")
    results = []
    state = {}

    def case(identifier, step):
        try:
            passed, observed = step()
        except Exception as error:  # noqa: BLE001 - a broken step fails its case, with the reason.
            passed, observed = (
                False,
                {"error": f"{type(error).__name__}: {error}"[:600]},
            )
        results.append(
            {
                "case": identifier,
                "verdict": "pass" if passed else "fail",
                "observed": observed,
            }
        )

    def iso_01():
        reaches, code = node_reaches_registry()
        keeplane = pods("keeplane")
        images = {}
        for pod in keeplane:
            spec = pod["spec"]
            for container in spec.get("initContainers", []) + spec["containers"]:
                images[container["image"]] = container.get("imagePullPolicy")
        pinned = all("@sha256:" in image for image in images) and (
            APP_IMAGE.startswith(MIRROR + "/") and APP_IMAGE in images
        )
        # While the runner still forwards everything, only the egress
        # policy can stop the app and gateway reaching outside addresses:
        # pods with no policy reach the same addresses.
        outside = [INTERNET, state.setdefault("registry", registry_target())]
        visitor = probe("visitor", outside)
        control = probe("model", outside)
        app = probe("app", outside)
        gateway = probe_gateway(outside)
        # Control for ISO-02: before closing, outside names resolve.
        names_before = {
            "node": lookup("node", [REGISTRY_HOST]),
            "visitor": lookup("visitor", [REGISTRY_HOST]),
        }
        return (
            reaches
            and all(resolved(found, REGISTRY_HOST) for found in names_before.values())
            and keeplane
            and all(ready(pod) for pod in keeplane)
            and pinned
            and all(visitor[t["name"]] == "open" for t in outside)
            and all(control[t["name"]] == "open" for t in outside)
            and blocked(app, "internet", "registry")
            and blocked(gateway, "internet", "registry"),
            {
                "node_registry_status": code,
                "pods_ready": {p["metadata"]["name"]: ready(p) for p in keeplane},
                "images": images,
                "registry_address": outside[1]["host"],
                "lookups_before_closing": names_before,
                "before_closing": {
                    "visitor": visitor,
                    "unrestricted_pod_in_keeplane": control,
                    "app": app,
                    "gateway_copy_0": gateway,
                },
            },
        )

    def node(*command, timeout=150):
        return run("docker", "exec", NODE, *command, check=False, timeout=timeout)

    def iso_02():
        # Control: before closing, the node pulls the same reference, then
        # forgets it, so the pull after closing can fail only for want of
        # the registry, not because the reference is wrong.
        absent_before = (
            node("crictl", "inspecti", ABSENT_IMAGE, timeout=60).returncode != 0
        )
        # Both pulls go straight to the outside registry (ctr reads no
        # registry hosts settings), not through the internal one, which does
        # not hold this image.
        control_pull = node("timeout", "120", *OUTSIDE_PULL, ABSENT_IMAGE, timeout=180)
        node("crictl", "rmi", ABSENT_IMAGE, timeout=60)
        forgotten = node("crictl", "inspecti", ABSENT_IMAGE, timeout=60).returncode != 0
        closed = run("sudo", str(CLOSE), timeout=300)
        # A CoreDNS replica that is still stopping can answer from its cache
        # (30 s) for a moment, so wait up to 90 s for outside names to go.
        started = time.monotonic()
        while True:
            names = {
                "node": lookup("node", [REGISTRY_HOST]),
                "app": lookup("app", [REGISTRY_HOST, APP_NAME]),
                "visitor": lookup("visitor", [REGISTRY_HOST, INSIDE_NAME]),
            }
            waited = round(time.monotonic() - started)
            if waited > 90 or all(
                unresolved(found, REGISTRY_HOST) for found in names.values()
            ):
                break
            time.sleep(5)
        reaches, code = node_reaches_registry()
        pull = node("timeout", "90", *OUTSIDE_PULL, ABSENT_IMAGE)
        error = (pull.stderr.strip() or pull.stdout.strip())[-300:]
        reference_rejected = any(
            text in error.lower()
            for text in ("not found", "manifest unknown", "unauthorized", "denied")
        )
        visitor = probe(
            "visitor",
            [MODEL, INTERNET, state.setdefault("registry", registry_target())],
        )
        return (
            absent_before
            and control_pull.returncode == 0
            and forgotten
            and all(unresolved(found, REGISTRY_HOST) for found in names.values())
            and resolved(names["app"], APP_NAME)
            and resolved(names["visitor"], INSIDE_NAME)
            and not reaches
            and pull.returncode != 0
            and not reference_rejected
            and blocked(visitor, "internet", "registry")
            and visitor["model"] == "open:200",
            {
                "image_absent_before": absent_before,
                "control_pull_exit_before_closing": control_pull.returncode,
                "image_removed_after_control": forgotten,
                "rules": closed.stdout.strip().splitlines(),
                "lookups_after_closing": names,
                "seconds_until_outside_names_failed": waited,
                "node_registry_status": code,
                "node_pull_exit": pull.returncode,
                "node_pull_error": error,
                "visitor": visitor,
            },
        )

    def iso_03():
        before = {p["metadata"]["uid"] for p in pods("keeplane")}
        before |= {
            p["metadata"]["uid"]
            for p in pods("ingress-nginx", "app.kubernetes.io/component=controller")
        }
        kubectl("-n", "keeplane", "delete", "pod", "--all", "--wait=true", timeout=400)
        kubectl(
            "-n",
            "ingress-nginx",
            "delete",
            "pod",
            "-l",
            "app.kubernetes.io/component=controller",
            "--wait=true",
            timeout=400,
        )
        wait_for_workloads()
        after = pods("keeplane") + pods(
            "ingress-nginx", "app.kubernetes.io/component=controller"
        )
        uids = {p["metadata"]["uid"] for p in after}
        events = []
        for namespace in ("keeplane", "ingress-nginx"):
            for event in json.loads(
                kubectl("-n", namespace, "get", "events", "-o", "json")
            )["items"]:
                if event["involvedObject"].get("uid") in uids:
                    events.append((event.get("reason"), event.get("message", "")))
        pulls = [
            e
            for e in events
            if e[0] == "Pulling" or "ErrImagePull" in e[1] or "ImagePullBackOff" in e[1]
        ]
        present = sum(
            1 for e in events if e[0] == "Pulled" and "already present" in e[1]
        )
        return (
            after
            and not (uids & before)
            and all(ready(p) for p in after)
            and not pulls,
            {
                "restarted": sorted(p["metadata"]["name"] for p in after),
                "pull_attempts": pulls,
                "images_already_present_events": present,
            },
        )

    def iso_04():
        status, page = fetch("/", attempts=40)
        health, _ = fetch("/health", attempts=5)
        font_status, font = fetch("/fonts/IBMPlexSans-Regular.woff2", attempts=5)
        # The controller was just restarted (ISO-03): its Service can refuse
        # for a moment after the pod reports ready, so retry for a minute.
        for _ in range(20):
            visit = run(
                "kubectl",
                "--kubeconfig",
                KUBECONFIG,
                "-n",
                "inside",
                "exec",
                "visitor",
                "--",
                "python",
                "-c",
                INSIDE_UI,
                check=False,
                timeout=60,
            )
            inside = visit.stdout.strip() or "".join(
                visit.stderr.strip().splitlines()[-1:]
            )
            if visit.returncode == 0:
                break
            time.sleep(3)
        return (
            status == 200
            and b'id="root"' in page
            and health == 200
            and font_status == 200
            and font[:4] == b"wOF2"
            and inside.startswith("HTTP/1.1 200")
            and inside.endswith("True"),
            {
                "runner_page": status,
                "health": health,
                "bundled_font": font_status,
                "visitor_through_ingress": inside,
            },
        )

    def iso_05():
        opener = sign_in()
        state["opener"] = opener
        key = (RUNTIME / "cloud-provider-key").read_text().strip()
        add_status, added = api(
            opener,
            "/api/models",
            {
                "name": "outside-cloud",
                "model": "mock-cloud",
                "source": "openai",
                "key_choice": "shared",
                "shared_key": key,
                "approved_classes": ["Public"],
            },
        )
        before = provider_calls()
        ask_status, answer = ask(opener, "outside-cloud")
        after = provider_calls()
        list_status, listing = api(opener, "/api/models")
        listed = {m["id"]: m for m in listing.get("models", [])}
        return (
            add_status == 200
            and list_status == 200
            and ask_status == 200
            and answer.get("answer") == "mock cloud answer"
            and after > before
            and listed.get("outside-cloud", {}).get("kind") == "cloud",
            {
                "add_status": add_status,
                "add_error": added.get("error"),
                "ask_status": ask_status,
                "answer": answer.get("answer") or answer.get("error"),
                "provider_calls": [before, after],
                "listed": sorted(listed),
            },
        )

    def iso_06():
        opener = state.get("opener") or sign_in()
        status, listing = api(opener, "/api/models")
        fixture = next(
            (m for m in listing.get("models", []) if m["id"] == "local-fixture"), {}
        )
        setup = None
        if not fixture.get("approved"):
            setup, _ = api(
                opener,
                "/api/models/local-fixture/setup",
                {"key_choice": "none", "approved_classes": ["Public"]},
            )
        before = provider_calls()
        ask_status, answer = ask(opener, "local-fixture", "fixture")
        after = provider_calls()
        return (
            status == 200
            and ask_status == 200
            and answer.get("answer") == "mock answer"
            and after == before,
            {
                "setup_status": setup,
                "ask_status": ask_status,
                "answer": answer.get("answer") or answer.get("error"),
                "outside_provider_calls": [before, after],
            },
        )

    def iso_07():
        targets = [
            MODEL,
            INSIDE,
            INTERNET,
            state.setdefault("registry", registry_target()),
        ]
        app = probe("app", targets)
        gateway = probe_gateway(targets)
        control = probe("model", [INSIDE])
        return (
            app["model"] == "open:200"
            and gateway["model"] == "open:200"
            and blocked(app, "inside_service", "internet", "registry")
            and blocked(gateway, "inside_service", "internet", "registry")
            and control["inside_service"] == "open:200",
            {"app": app, "gateway_copy_0": gateway, "unrestricted_pod": control},
        )

    def iso_08():
        visitor = probe("visitor", [APP, GATEWAY, IN_CLUSTER_MODEL])
        neighbour = probe("model", [APP, GATEWAY])
        return (
            blocked(visitor, "app", "gateway")
            and blocked(neighbour, "app", "gateway")
            and visitor["in_cluster_model"] == "open:200",
            {"visitor_in_inside": visitor, "unlabelled_pod_in_keeplane": neighbour},
        )

    def journey():
        """The web UI, sign-in and both models, with the network still closed."""
        status, page = fetch("/", attempts=60)
        opener = sign_in()
        cloud_status, cloud = ask(opener, "outside-cloud")
        local_status, local = ask(opener, "local-fixture", "fixture")
        reaches, code = node_reaches_registry()
        app = probe(
            "app", [MODEL, INTERNET, state.setdefault("registry", registry_target())]
        )
        names = {
            "node": lookup("node", [REGISTRY_HOST]),
            "app": lookup("app", [REGISTRY_HOST, APP_NAME]),
        }
        return (
            status == 200
            and b'id="root"' in page
            and cloud.get("answer") == "mock cloud answer"
            and local.get("answer") == "mock answer"
            and not reaches
            and blocked(app, "internet", "registry")
            and all(unresolved(found, REGISTRY_HOST) for found in names.values())
            and resolved(names["app"], APP_NAME),
            {
                "page": status,
                "outside_cloud": [
                    cloud_status,
                    cloud.get("answer") or cloud.get("error"),
                ],
                "local_fixture": [
                    local_status,
                    local.get("answer") or local.get("error"),
                ],
                "node_registry_status": code,
                "app": app,
                "lookups": names,
            },
        )

    def iso_09():
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        run("docker", "restart", NODE, timeout=180)
        wait_for_node()
        wait_for_workloads()
        fresh = wait_for_restarted_pods(since, RESTARTED)
        passed, observed = journey()
        observed["pods_restarted_and_ready"] = fresh
        return passed and all(fresh.values()), observed

    def iso_10():
        mirrored = json.loads(MIRRORED.read_text())
        held = {
            (e["registry"], e["path"].removeprefix(e["registry"] + "/"), e["digest"])
            for e in mirrored
        }
        used = installed_images()
        missing = sorted(ref for ref in used if mirror_key(ref) not in held)
        # From the node, with the outside registries closed: every image the
        # internal registry holds is served by its digest, and for an image
        # index the linux/amd64 image under it too.
        served = {}
        for entry in mirrored:
            for digest in filter(None, (entry["digest"], entry.get("platform_digest"))):
                served[f"{entry['path']}@{digest}"] = (
                    node_manifest(entry["path"], digest) == digest
                )
        reaches, code = node_reaches_registry()
        return (
            mirrored and used and not missing and all(served.values()) and not reaches,
            {
                "images_in_use_outside_the_node_image": sorted(used),
                "not_in_internal_registry": missing,
                "served_to_the_node": served,
                "node_registry_status": code,
            },
        )

    def iso_11():
        _, node_ids = node_image()
        used = installed_images(ephemeral=False)
        # The node forgets every image the install brought: kubelet stops
        # so it pulls nothing meanwhile, and every image the node image did
        # not hold is removed. Only Kubernetes' own images stay.
        node("systemctl", "stop", "kubelet")
        listed = json.loads(node("crictl", "images", "-o", "json").stdout)["images"]
        removed = []
        for image in listed:
            if image["id"] not in node_ids:
                node("crictl", "rmi", image["id"], timeout=120)
                removed += image.get("repoDigests") or image.get("repoTags") or []
        left = json.loads(node("crictl", "images", "-o", "json").stdout)["images"]
        extra = sorted(i["id"] for i in left if i["id"] not in node_ids)
        still_held = sorted(
            ref
            for ref in used
            if node("crictl", "inspecti", ref, timeout=60).returncode == 0
        )
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        run("docker", "restart", NODE, timeout=180)
        wait_for_node()
        wait_for_workloads()

        def held(ref):
            return node("crictl", "inspecti", ref, timeout=60).returncode == 0

        fresh = wait_for_restarted_pods(
            since, RESTARTED, until=lambda: all(held(ref) for ref in used)
        )
        address = node_address()
        fetched = {
            (path, status)
            for client, path, status in mirror_requests(since)
            if client == address
        }
        from_mirror = {}
        for ref in used:
            registry, path, digest = mirror_key(ref)
            target = MIRROR_TOOL.mirror_path(registry, path)
            from_mirror[ref] = (f"/v2/{target}/manifests/{digest}", "200") in fetched
        back = {ref: held(ref) for ref in used}
        reaches, code = node_reaches_registry()
        return (
            removed
            and not extra
            and not still_held
            and all(from_mirror.values())
            and all(back.values())
            and all(fresh.values())
            and not reaches,
            {
                "images_removed": len(removed),
                "left_beyond_the_node_image": extra,
                "still_held_after_removal": still_held,
                "pulled_from_internal_registry": from_mirror,
                "held_again": back,
                "pods_restarted_and_ready": fresh,
                "node_registry_status": code,
            },
        )

    def iso_12():
        passed, observed = journey()
        gateway = probe_gateway(
            [MODEL, INTERNET, state.setdefault("registry", registry_target())]
        )
        observed["gateway_copy_0"] = gateway
        return (
            passed
            and gateway["model"] == "open:200"
            and blocked(gateway, "internet", "registry"),
            observed,
        )

    for identifier, step in (
        ("ISO-01", iso_01),
        ("ISO-02", iso_02),
        ("ISO-03", iso_03),
        ("ISO-04", iso_04),
        ("ISO-05", iso_05),
        ("ISO-06", iso_06),
        ("ISO-07", iso_07),
        ("ISO-08", iso_08),
        ("ISO-09", iso_09),
        ("ISO-10", iso_10),
        ("ISO-11", iso_11),
        ("ISO-12", iso_12),
    ):
        case(identifier, step)

    print(
        json.dumps(
            {"suite": "Keeplane on an isolated network", "results": results}, indent=2
        )
    )
    return 1 if any(r["verdict"] == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(run_cases())


def test_kubernetes_isolated(monkeypatch, report_file, request, capsys):
    monkeypatch.setattr("sys.argv", [__file__])
    status = run_cases()
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    assert status in (None, 0)
    verify_cases(__file__, output.out, globals().get("REPORT", report_file))


pytestmark = [pytest.mark.kubernetes]
