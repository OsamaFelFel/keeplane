"""Cases KCA-01 to KCA-04 in kubernetes-private-ca-cases.md, on the kind preview.

The kind preview's fixture provider serves HTTPS with a test CA that
deploy/local/kind-up.sh makes, and the chart's trust.extraCaBundle names it
(deploy/local/values.yaml). These cases check that the app copies and the
gateway copies trust that CA beside their system CAs, and that a cloud model
answers over HTTPS through every gateway copy. KCA-04 also runs the pinned
gateway image with Docker on this machine, to check its system CA file is read
beside the private CA. They refuse any Kubernetes context but kind-keeplane and
never print a key.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from tests.support.client import RUNTIME, Browser
from tests.support.kind_trial import CONTEXT, kind_kubeconfig

KUBECONFIG = kind_kubeconfig()
BASE = os.environ.get("KEEPLANE_BASE_URL", "http://127.0.0.1:13000")
NAMESPACE = "keeplane"
BUNDLE = "/run/keeplane-trust/ca-bundle.pem"
EXTRA_DIR = "/run/keeplane-extra-ca"
# The system CA file the chart names for the gateway copies (_trust.tpl).
GATEWAY_SYSTEM_CAS = "/etc/ssl/certs/ca-certificates.crt"
ROOT = Path(__file__).resolve().parents[2]

# Run in the app container: how its trust file compares with the image's own
# system CA file, and how many CAs Python's default context loads from it.
BUNDLE_SCRIPT = """
import json, os, ssl, sys
system = open(ssl.get_default_verify_paths().openssl_cafile, "rb").read()
bundle = open(sys.argv[1], "rb").read()
marker = b"-----BEGIN CERTIFICATE-----"
print(json.dumps({
    "ssl_cert_file": os.environ.get("SSL_CERT_FILE"),
    "system": system.count(marker),
    "bundle": bundle.count(marker),
    "starts_with_system": bundle.startswith(system.rstrip(b"\\n")),
    "ends_with_extra": ssl.PEM_cert_to_DER_cert(
        marker.decode() + bundle.rsplit(marker, 1)[1].decode()
    ) == ssl.PEM_cert_to_DER_cert(sys.argv[2]),
    "loaded": ssl.create_default_context().cert_store_stats()["x509_ca"],
}))
"""
# Run in the app container: one chat request straight to one gateway copy,
# with the app's runtime key, as K8S-02 reads each copy.
COPY_SCRIPT = """
import json, pathlib, sys, urllib.error, urllib.request
key = pathlib.Path("/run/gateway-keys/runtime-key").read_text().strip()
request = urllib.request.Request(
    sys.argv[1] + "/v1/chat/completions",
    data=json.dumps({"model": sys.argv[2],
                     "messages": [{"role": "user", "content": "Say hello"}]}).encode(),
    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
        print(json.dumps({"status": response.status,
                          "answer": body["choices"][0]["message"]["content"]}))
except urllib.error.HTTPError as error:
    print(json.dumps({"status": error.code, "answer": error.read(300).decode()}))
"""
# Run in the fixture pod: its record of answers and of the key hashes it was sent.
CALLS_SCRIPT = (
    "import ssl, urllib.request; print(urllib.request.urlopen("
    "'https://cloud-provider:18443/calls', timeout=10, context="
    "ssl.create_default_context(cafile='/run/tls/ca.pem')).read().decode())"
)


def kubectl(*args):
    return subprocess.check_output(
        ["kubectl", "--kubeconfig", KUBECONFIG, *args], text=True, timeout=120
    ).strip()


def in_pod(target, container, script, *args):
    output = kubectl(
        "-n",
        NAMESPACE,
        "exec",
        target,
        "-c",
        container,
        "--",
        "python",
        "-c",
        script,
        *args,
    )
    return json.loads(output.splitlines()[-1])


def env_of(container):
    return {item["name"]: item.get("value") for item in container.get("env", [])}


def gateway_pods():
    pods = json.loads(
        kubectl(
            "-n",
            NAMESPACE,
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/component=standalone",
            "-o",
            "json",
        )
    )["items"]
    return [
        pod
        for pod in pods
        if pod["status"].get("phase") == "Running"
        and pod["metadata"].get("deletionTimestamp") is None
    ]


def fixture_state():
    return in_pod("deploy/cloud-provider", "cloud-provider", CALLS_SCRIPT)


# KCA-04 runs the pinned gateway image with Docker on this machine, as the
# chart configures it: SSL_CERT_FILE names the image's system CA file and
# SSL_CERT_DIR a folder that prepare_trust_bundle.py --extra-only filled.
GATEWAY_CONFIG = """config: {{}}
gateways:
  default:
    port: 4000
llm:
  models:
    - name: private
      provider: {{custom: {{formats: [{{type: completions}}]}}}}
      params: {{model: mock-cloud, baseUrl: "https://kca-private:18443/v1", apiKey: {key}}}
    - name: system
      provider: {{custom: {{formats: [{{type: completions}}]}}}}
      params: {{model: mock-cloud, baseUrl: "https://kca-system:18443/v1", apiKey: {key}}}
"""
ASK_SCRIPT = """
import json, sys, time, urllib.error, urllib.request
answers = {}
for model in ("private", "system"):
    deadline = time.monotonic() + 60
    while True:
        request = urllib.request.Request(
            "http://kca-gateway:4000/v1/chat/completions",
            data=json.dumps({"model": model,
                             "messages": [{"role": "user", "content": "hi"}]}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                answers[model] = json.load(response)["choices"][0]["message"]["content"]
            break
        except urllib.error.HTTPError as error:
            answers[model] = error.read(200).decode()
            break
        except OSError as error:
            if time.monotonic() > deadline:
                answers[model] = str(error)
                break
            time.sleep(1)
print(json.dumps(answers))
"""


def docker(*args, check=True):
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=600, check=False
    )
    if check and result.returncode:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr.strip()[-300:]}")
    return result


def gateway_image_check(gateway_image, python_image):
    """KCA-04: the pinned image's system CA file, loaded beside a private CA."""
    from tests.unit.test_certificate_checks import make_ca, make_leaf

    docker("pull", "-q", gateway_image)
    image_env = json.loads(
        docker(
            "image", "inspect", gateway_image, "--format", "{{json .Config.Env}}"
        ).stdout
    )
    suffix = uuid.uuid4().hex[:8]
    network, started = f"kca-{suffix}", []
    with tempfile.TemporaryDirectory(prefix="kca-") as work:
        work = Path(work)
        holder = docker("create", gateway_image).stdout.strip()
        try:
            docker("cp", f"{holder}:{GATEWAY_SYSTEM_CAS}", str(work / "system.pem"))
        finally:
            docker("rm", "-f", holder, check=False)
        system = (work / "system.pem").read_bytes()
        count = system.count(b"-----BEGIN CERTIFICATE-----")
        # A private CA for one endpoint; a second CA stands in for a public
        # one and is appended to a copy of the image's system file, mounted at
        # the same path, so an answer from its endpoint proves that file is read.
        make_ca(work, "private-ca")
        make_ca(work, "system-ca")
        for name, ca in (("kca-private", "private-ca"), ("kca-system", "system-ca")):
            folder = work / name
            folder.mkdir()
            cert, key = make_leaf(work, ca, name, names=f"DNS:{name}")
            (folder / "provider.pem").write_bytes(cert.read_bytes())
            (folder / "provider.key").write_bytes(key.read_bytes())
        (work / "system-plus.pem").write_bytes(
            system.rstrip(b"\n") + b"\n" + (work / "system-ca.crt").read_bytes()
        )
        (work / "extra").mkdir()
        prepared = subprocess.run(
            [
                sys.executable,
                "-I",
                str(ROOT / "components/control-plane/prepare_trust_bundle.py"),
                "--extra-only",
                str(work / "private-ca.crt"),
                str(work / "extra/ca.crt"),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        key = "kca-" + uuid.uuid4().hex
        (work / "key").write_text(key + "\n")
        (work / "gateway.yaml").write_text(GATEWAY_CONFIG.format(key=key))
        for path in [work, *work.rglob("*")]:
            path.chmod(0o755 if path.is_dir() else 0o644)
        try:
            docker("network", "create", network)
            for name in ("kca-private", "kca-system"):
                started.append(name + "-" + suffix)
                docker(
                    "run",
                    "-d",
                    "--name",
                    started[-1],
                    "--network",
                    network,
                    "--network-alias",
                    name,
                    "-e",
                    "TRIAL_KEY_FILE=/run/key",
                    "-e",
                    "TLS_CERT_FILE=/run/tls/provider.pem",
                    "-e",
                    "TLS_KEY_FILE=/run/tls/provider.key",
                    "-v",
                    f"{work / 'key'}:/run/key:ro",
                    "-v",
                    f"{work / name}:/run/tls:ro",
                    "-v",
                    f"{ROOT / 'tests/fixtures/cloud_provider.py'}:/c.py:ro",
                    python_image,
                    "python",
                    "/c.py",
                )

            def answers(*settings):
                gateway = "kca-gateway-" + suffix
                started.append(gateway)
                docker(
                    "run",
                    "-d",
                    "--name",
                    gateway,
                    "--network",
                    network,
                    "--network-alias",
                    "kca-gateway",
                    "-e",
                    "IPV6_ENABLED=false",
                    "-e",
                    "READINESS_ADDR=0.0.0.0:15021",
                    "-e",
                    "STATS_ADDR=0.0.0.0:15020",
                    *settings,
                    "-v",
                    f"{work / 'system-plus.pem'}:{GATEWAY_SYSTEM_CAS}:ro",
                    "-v",
                    f"{work / 'extra'}:{EXTRA_DIR}:ro",
                    "-v",
                    f"{work / 'gateway.yaml'}:/gateway.yaml:ro",
                    gateway_image,
                    "-f",
                    "/gateway.yaml",
                )
                try:
                    output = docker(
                        "run",
                        "--rm",
                        "--network",
                        network,
                        python_image,
                        "python",
                        "-c",
                        ASK_SCRIPT,
                    ).stdout
                    return json.loads(output.strip().splitlines()[-1])
                finally:
                    docker("rm", "-f", gateway, check=False)
                    started.remove(gateway)

            chart_settings = answers(
                "-e",
                f"SSL_CERT_FILE={GATEWAY_SYSTEM_CAS}",
                "-e",
                f"SSL_CERT_DIR={EXTRA_DIR}",
            )
            without_folder = answers("-e", f"SSL_CERT_FILE={GATEWAY_SYSTEM_CAS}")
        finally:
            for name in started:
                docker("rm", "-f", name, check=False)
            docker("network", "rm", network, check=False)
    return {
        "image": gateway_image,
        "image_ssl_cert_file": next(
            (
                item.split("=", 1)[1]
                for item in image_env
                if item.startswith("SSL_CERT_FILE=")
            ),
            None,
        ),
        "system_cas": count,
        "prepared": prepared.stdout.strip(),
        "chart_settings": chart_settings,
        "without_folder": without_folder,
    }


def run_cases():
    context = kubectl("config", "current-context")
    if context != CONTEXT:
        raise SystemExit(f"Refusing Kubernetes context {context!r}; expected {CONTEXT}")
    results = []

    def check(case, okay, observed):
        results.append(
            {"case": case, "verdict": "pass" if okay else "fail", "observed": observed}
        )

    # KCA-01: the app's trust file is the system CA file plus the test CA;
    # each gateway copy names its system CA file and reads the checked test CA.
    test_ca = json.loads(
        kubectl("-n", NAMESPACE, "get", "configmap", "cloud-provider-ca", "-o", "json")
    )["data"]["ca.crt"].strip()
    app = json.loads(
        kubectl("-n", NAMESPACE, "get", "deployment", "keeplane-app", "-o", "json")
    )["spec"]["template"]["spec"]
    app_container = next(c for c in app["containers"] if c["name"] == "app")
    bundle = in_pod("deploy/keeplane-app", "app", BUNDLE_SCRIPT, BUNDLE, test_ca)
    copies = []
    for pod in gateway_pods():
        container = next(
            c for c in pod["spec"]["containers"] if c["name"] == "agentgateway"
        )
        volumes = {v["name"]: v for v in pod["spec"]["volumes"]}
        steps = {
            status["name"]: (status.get("state", {}).get("terminated") or {}).get(
                "exitCode"
            )
            for status in pod["status"].get("initContainerStatuses", [])
        }
        copies.append(
            {
                "pod": pod["metadata"]["name"],
                "ssl_cert_file": env_of(container).get("SSL_CERT_FILE"),
                "ssl_cert_dir": env_of(container).get("SSL_CERT_DIR"),
                "mounts": sorted(
                    m["name"]
                    for m in container.get("volumeMounts", [])
                    if m["name"].startswith("keeplane-extra-ca")
                ),
                "checked_folder": volumes.get("keeplane-extra-ca", {})
                .get("emptyDir", {})
                .get("medium"),
                "source": volumes.get("keeplane-extra-ca-source", {})
                .get("configMap", {})
                .get("name"),
                "init_exit": steps.get("prepare-trust-bundle"),
                "init_log": kubectl(
                    "-n",
                    NAMESPACE,
                    "logs",
                    pod["metadata"]["name"],
                    "-c",
                    "prepare-trust-bundle",
                ),
            }
        )
    check(
        "KCA-01",
        env_of(app_container).get("SSL_CERT_FILE") == BUNDLE
        and bundle["ssl_cert_file"] == BUNDLE
        and bundle["system"] > 0
        and bundle["bundle"] == bundle["system"] + 1
        and bundle["starts_with_system"]
        and bundle["ends_with_extra"]
        and bundle["loaded"] >= bundle["system"] + 1
        and len(copies) == 2
        and all(
            copy["ssl_cert_file"] == GATEWAY_SYSTEM_CAS
            and copy["ssl_cert_dir"] == EXTRA_DIR
            # Only the checked folder: the raw source stays in the init step.
            and copy["mounts"] == ["keeplane-extra-ca"]
            and copy["checked_folder"] == "Memory"
            and copy["source"] == "cloud-provider-ca"
            and copy["init_exit"] == 0
            and copy["init_log"] == "Extra CAs written for the gateway: 1."
            for copy in copies
        ),
        {"app": bundle, "gateway_copies": copies},
    )

    browser = Browser(BASE)
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    shared_key = (RUNTIME / "cloud-provider-key").read_text().strip()
    shared_hash = hashlib.sha256(shared_key.encode()).hexdigest()
    suffix = uuid.uuid4().hex[:8]
    own, shared = f"kca-own-{suffix}", f"kca-shared-{suffix}"
    added = []
    try:
        # KCA-02: adding a model for developers' own keys makes the app check
        # the provider over HTTPS, which it trusts only through the test CA.
        status, body, _ = browser.fetch(
            "/api/models",
            {
                "name": own,
                "model": own,
                "source": "openai",
                "key_choice": "personal",
                "approved_classes": ["Public"],
            },
            method="POST",
        )
        if status == 200:
            added.append(own)
        _, listing, _ = browser.fetch("/api/models")
        listed = next(
            (m for m in (listing or {}).get("models", []) if m.get("id") == own), None
        )
        check(
            "KCA-02",
            status == 200
            and listed is not None
            and listed.get("key_choice") == "personal",
            {
                "status": status,
                "error": (body or {}).get("error"),
                "key_choice": (listed or {}).get("key_choice"),
            },
        )

        # KCA-03: a shared-key model answers over HTTPS through the gateway
        # Service and through each gateway copy directly.
        before = fixture_state()["keys"].get(shared_hash, {}).get("accepted", 0)
        status, body, _ = browser.fetch(
            "/api/models",
            {
                "name": shared,
                "model": shared,
                "source": "openai",
                "key_choice": "shared",
                "shared_key": shared_key,
                "approved_classes": ["Public"],
            },
            method="POST",
        )
        if status == 200:
            added.append(shared)
        ask_status, answer, _ = browser.fetch(
            "/api/ask", {"model": shared, "prompt": "Say hello"}, method="POST"
        )
        direct = [
            {
                "pod": pod["metadata"]["name"],
                **in_pod(
                    "deploy/keeplane-app",
                    "app",
                    COPY_SCRIPT,
                    f"http://{pod['status']['podIP']}:4000",
                    shared,
                ),
            }
            for pod in gateway_pods()
        ]
        state = fixture_state()
        after = state["keys"].get(shared_hash, {}).get("accepted", 0)
        check(
            "KCA-03",
            status == 200
            and ask_status == 200
            and (answer or {}).get("answer") == "mock cloud answer"
            and len(direct) == 2
            and all(
                item["status"] == 200 and item["answer"] == "mock cloud answer"
                for item in direct
            )
            # The Service answer and one per copy, all on the shared key.
            and after - before >= 3,
            {
                "add_status": status,
                "add_error": (body or {}).get("error"),
                "ask_status": ask_status,
                "answer": (answer or {}).get("answer"),
                "copies": direct,
                "shared_key_answers": after - before,
            },
        )
    finally:
        for name in added:
            browser.fetch(f"/api/models/{name}/setup", {}, method="DELETE")

    # KCA-04: the pinned gateway image still has the system CA file the chart
    # names, and the gateway reads it together with the checked private CA.
    copy = gateway_pods()[0]
    gateway_image = next(
        c["image"] for c in copy["spec"]["containers"] if c["name"] == "agentgateway"
    )
    python_image = json.loads(
        kubectl("-n", NAMESPACE, "get", "deployment", "cloud-provider", "-o", "json")
    )["spec"]["template"]["spec"]["containers"][0]["image"]
    image = gateway_image_check(gateway_image, python_image)
    check(
        "KCA-04",
        image["system_cas"] >= 50
        and image["image_ssl_cert_file"] == GATEWAY_SYSTEM_CAS
        and image["prepared"] == "Extra CAs written for the gateway: 1."
        and image["chart_settings"]
        == {"private": "mock cloud answer", "system": "mock cloud answer"}
        # Without the folder only the system file's CAs are trusted.
        and image["without_folder"]["system"] == "mock cloud answer"
        and image["without_folder"]["private"] != "mock cloud answer",
        image,
    )

    print(
        json.dumps(
            {"suite": "Keeplane kind preview with a private CA", "results": results},
            indent=2,
        )
    )
    return 1 if any(r["verdict"] == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(run_cases())


def test_kind_private_ca(monkeypatch, report_file, capsys):
    monkeypatch.setattr("sys.argv", [__file__])
    assert run_cases() in (None, 0)
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    verify_cases(__file__, output.out, globals().get("REPORT", report_file))


pytestmark = [pytest.mark.kubernetes]
