"""Run the isolated-network cases (kubernetes-isolated-cases.md) on kind.

The cluster is the disposable `keeplane-isolated` kind cluster the Kubernetes
isolated network workflow creates: Calico enforces NetworkPolicy, ingress-nginx
publishes Keeplane on https://keeplane.isolated.test, and the model provider
fixture runs on the runner outside the cluster. The cases close the network's
outside access themselves (ISO-02), restart every Keeplane pod and then the
node, and run the admin journey with only the model provider reachable.

They refuse any kubeconfig context other than kind-keeplane-isolated, and
change the runner's firewall, so they run only in that workflow.
"""

import pytest

import http.cookiejar
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import (
    HTTPCookieProcessor,
    HTTPSHandler,
    Request,
    build_opener,
    urlopen,
)

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
APP_IMAGE = "keeplane-preview:kind-local"
CLOSE = ROOT / "tests/fixtures/isolated-network/close-network.sh"
# An image the node never had, for the registry pull check.
ABSENT_IMAGE = "registry.k8s.io/e2e-test-images/agnhost:2.53"

# Runs in a pod: try each target and report "open", "open:<HTTP status>" or
# "blocked:<error>". A dropped connection times out.
PROBE = """import json,socket,sys,urllib.error,urllib.request
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
  out[t["name"]]="blocked:"+type(e).__name__
print(json.dumps(out))"""

# Runs in the visitor pod: open the web UI through the ingress controller's
# Service with the run's CA, as a browser inside the network would.
INSIDE_UI = """import socket,ssl
c=ssl.create_default_context(cafile="/ca/ca.crt")
s=c.wrap_socket(socket.create_connection(("ingress-nginx-controller.ingress-nginx.svc.cluster.local",443),timeout=10),server_hostname="keeplane.isolated.test")
s.sendall(b"GET / HTTP/1.1\\r\\nHost: keeplane.isolated.test\\r\\nConnection: close\\r\\n\\r\\n")
d=b""
while True:
 b=s.recv(65536)
 if not b:
  break
 d+=b
print(d.split(b"\\r\\n",1)[0].decode(), b'id="root"' in d)"""

MODEL = {"name": "model", "host": PROVIDER, "port": PROVIDER_PORT, "path": "/health"}
INTERNET = {"name": "internet", "host": "1.1.1.1", "port": 443}
REGISTRY = {"name": "registry", "host": "registry.k8s.io", "port": 443}
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
GATEWAY = {"name": "gateway", "host": "keeplane.keeplane.svc.cluster.local", "port": 4000}
IN_CLUSTER_MODEL = {
    "name": "in_cluster_model",
    "host": "model.keeplane.svc.cluster.local",
    "port": 18080,
    "path": "/health",
}
OUTSIDE = (INTERNET, REGISTRY)


def run(*command, timeout=300, check=True):
    result = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, timeout=timeout
    )
    if check and result.returncode:
        raise RuntimeError(f"{' '.join(command[:4])} failed: {result.stderr[-400:]}")
    return result


def kubectl(*args, timeout=300):
    return run("kubectl", "--kubeconfig", KUBECONFIG, *args, timeout=timeout).stdout


def probe(where, targets):
    """Probe from a pod: ("app" | "model" | "visitor")."""
    target = {
        "app": ("-n", "keeplane", "exec", "deploy/keeplane-app", "-c", "app"),
        "model": ("-n", "keeplane", "exec", "deploy/model"),
        "visitor": ("-n", "inside", "exec", "visitor"),
    }[where]
    output = kubectl(*target, "--", "python", "-c", PROBE, json.dumps(targets))
    return json.loads(output)


GATEWAY_PROBES = [0]


def probe_gateway(targets):
    """Probe from inside gateway copy 0's network with an ephemeral container.

    The gateway image has no shell or Python, so a pinned Python container
    joins the Pod; the Pod's NetworkPolicy applies to it as to the gateway.
    """
    GATEWAY_PROBES[0] += 1
    name = f"probe-{int(time.time())}-{GATEWAY_PROBES[0]}"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as custom:
        json.dump({"securityContext": {"runAsUser": 65532, "runAsGroup": 65532}}, custom)
    try:
        kubectl(
            "-n", "keeplane", "debug", "pod/keeplane-gateway-0",
            "--image=" + PYTHON_IMAGE, "--image-pull-policy=IfNotPresent",
            "--container=" + name, "--profile=restricted", "--custom=" + custom.name,
            "--", "python", "-c", PROBE, json.dumps(targets),
        )
    finally:
        os.unlink(custom.name)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        pod = json.loads(kubectl("-n", "keeplane", "get", "pod", "keeplane-gateway-0", "-o", "json"))
        for status in pod["status"].get("ephemeralContainerStatuses", []):
            if status["name"] == name and "terminated" in status.get("state", {}):
                logs = kubectl("-n", "keeplane", "logs", "pod/keeplane-gateway-0", "-c", name)
                return json.loads(logs.strip().splitlines()[-1])
        time.sleep(2)
    raise RuntimeError("The gateway probe did not finish")


def blocked(observed, *names):
    return all(observed.get(name, "").startswith("blocked:") for name in names)


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
    status, _ = api(opener, "/api/session", {"username": "first-admin", "password": password})
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
        "docker", "exec", NODE, "curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}",
        "-m", "10", "https://registry.k8s.io/v2/", check=False, timeout=60,
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


def wait_for_workloads(timeout="300s"):
    for kind_name in (
        "deployment/keeplane-app",
        "statefulset/keeplane-gateway",
        "deployment/model",
        "deployment/postgres",
    ):
        kubectl("-n", "keeplane", "rollout", "status", kind_name, "--timeout=" + timeout, timeout=400)
    kubectl(
        "-n", "ingress-nginx", "rollout", "status", "deployment/ingress-nginx-controller",
        "--timeout=" + timeout, timeout=400,
    )
    kubectl("-n", "inside", "wait", "--for=condition=Ready", "pod", "--all", "--timeout=" + timeout, timeout=400)


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
        except Exception as error:  # A broken step fails its case, with the reason.
            passed, observed = False, {"error": f"{type(error).__name__}: {error}"[:600]}
        results.append(
            {"case": identifier, "verdict": "pass" if passed else "fail", "observed": observed}
        )

    def iso_01():
        reaches, code = node_reaches_registry()
        keeplane = pods("keeplane")
        images = {}
        for pod in keeplane:
            spec = pod["spec"]
            for container in spec.get("initContainers", []) + spec["containers"]:
                images[container["image"]] = container.get("imagePullPolicy")
        pinned = all(
            "@sha256:" in image or (image == APP_IMAGE and policy == "Never")
            for image, policy in images.items()
        )
        visitor = probe("visitor", [INTERNET])
        return (
            reaches
            and keeplane
            and all(ready(pod) for pod in keeplane)
            and pinned
            and visitor["internet"] == "open",
            {
                "node_registry_status": code,
                "pods_ready": {p["metadata"]["name"]: ready(p) for p in keeplane},
                "images": images,
                "visitor_internet_before_closing": visitor["internet"],
            },
        )

    def iso_02():
        closed = run("sudo", str(CLOSE), timeout=60)
        reaches, code = node_reaches_registry()
        pull = run(
            "docker", "exec", NODE, "timeout", "90", "crictl", "pull", ABSENT_IMAGE,
            check=False, timeout=150,
        )
        visitor = probe("visitor", [MODEL, *OUTSIDE])
        return (
            not reaches
            and pull.returncode != 0
            and blocked(visitor, "internet", "registry")
            and visitor["model"] == "open:200",
            {
                "rules": closed.stdout.strip().splitlines(),
                "node_registry_status": code,
                "node_pull_exit": pull.returncode,
                "node_pull_error": pull.stderr.strip()[-200:],
                "visitor": visitor,
            },
        )

    def iso_03():
        before = {p["metadata"]["uid"] for p in pods("keeplane")}
        before |= {p["metadata"]["uid"] for p in pods("ingress-nginx", "app.kubernetes.io/component=controller")}
        kubectl("-n", "keeplane", "delete", "pod", "--all", "--wait=true", timeout=400)
        kubectl("-n", "ingress-nginx", "delete", "pod", "-l", "app.kubernetes.io/component=controller", "--wait=true", timeout=400)
        wait_for_workloads()
        after = pods("keeplane") + pods("ingress-nginx", "app.kubernetes.io/component=controller")
        uids = {p["metadata"]["uid"] for p in after}
        events = []
        for namespace in ("keeplane", "ingress-nginx"):
            for event in json.loads(kubectl("-n", namespace, "get", "events", "-o", "json"))["items"]:
                if event["involvedObject"].get("uid") in uids:
                    events.append((event.get("reason"), event.get("message", "")))
        pulls = [
            e for e in events
            if e[0] == "Pulling" or "ErrImagePull" in e[1] or "ImagePullBackOff" in e[1]
        ]
        present = sum(1 for e in events if e[0] == "Pulled" and "already present" in e[1])
        return (
            after and not (uids & before) and all(ready(p) for p in after) and not pulls,
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
        inside = kubectl("-n", "inside", "exec", "visitor", "--", "python", "-c", INSIDE_UI).strip()
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
        fixture = next((m for m in listing.get("models", []) if m["id"] == "local-fixture"), {})
        setup = None
        if not fixture.get("approved"):
            setup, _ = api(
                opener,
                "/api/models/local-fixture/setup",
                {"key_choice": "none", "approved_classes": ["Public"]},
            )
        ask_status, answer = ask(opener, "local-fixture", "fixture")
        return (
            status == 200
            and ask_status == 200
            and answer.get("answer") == "mock answer",
            {
                "setup_status": setup,
                "ask_status": ask_status,
                "answer": answer.get("answer") or answer.get("error"),
            },
        )

    def iso_07():
        targets = [MODEL, INSIDE, *OUTSIDE]
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

    def iso_09():
        run("docker", "restart", NODE, timeout=180)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            nodes = run(
                "kubectl", "--kubeconfig", KUBECONFIG, "get", "nodes", "-o", "json",
                check=False, timeout=30,
            )
            if nodes.returncode == 0 and all(
                any(c["type"] == "Ready" and c["status"] == "True" for c in n["status"]["conditions"])
                for n in json.loads(nodes.stdout)["items"]
            ):
                break
            time.sleep(5)
        else:
            raise RuntimeError("The node did not come back Ready")
        kubectl("-n", "kube-system", "rollout", "status", "daemonset/calico-node", "--timeout=300s", timeout=400)
        wait_for_workloads()
        status, page = fetch("/", attempts=60)
        opener = sign_in()
        cloud_status, cloud = ask(opener, "outside-cloud")
        local_status, local = ask(opener, "local-fixture", "fixture")
        reaches, code = node_reaches_registry()
        app = probe("app", [MODEL, *OUTSIDE])
        return (
            status == 200
            and b'id="root"' in page
            and cloud.get("answer") == "mock cloud answer"
            and local.get("answer") == "mock answer"
            and not reaches
            and blocked(app, "internet", "registry"),
            {
                "page": status,
                "outside_cloud": [cloud_status, cloud.get("answer") or cloud.get("error")],
                "local_fixture": [local_status, local.get("answer") or local.get("error")],
                "node_registry_status": code,
                "app": app,
            },
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
    ):
        case(identifier, step)

    print(json.dumps({"suite": "Keeplane on an isolated network", "results": results}, indent=2))
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
