"""Cases KCA-01 to KCA-03 in kubernetes-private-ca-cases.md, on the kind preview.

The kind preview's fixture provider serves HTTPS with a test CA that
deploy/local/kind-up.sh makes, and the chart's trust.extraCaBundle names it
(deploy/local/values.yaml). These cases check that the app copies and the
gateway copies trust that CA beside their system CAs, and that a cloud model
answers over HTTPS through every gateway copy. They refuse any Kubernetes
context but kind-keeplane and never print a key.
"""

import hashlib
import json
import os
import subprocess
import sys
import uuid

import pytest

from tests.support.client import RUNTIME, Browser
from tests.support.kind_trial import CONTEXT, kind_kubeconfig

KUBECONFIG = kind_kubeconfig()
BASE = os.environ.get("KEEPLANE_BASE_URL", "http://127.0.0.1:13000")
NAMESPACE = "keeplane"
BUNDLE = "/run/keeplane-trust/ca-bundle.pem"
EXTRA_DIR = "/run/keeplane-extra-ca"

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


def run_cases():
    context = kubectl("config", "current-context")
    if context != CONTEXT:
        raise SystemExit(f"Refusing Kubernetes context {context!r}; expected {CONTEXT}")
    results = []

    def check(case, okay, observed):
        results.append(
            {"case": case, "verdict": "pass" if okay else "fail", "observed": observed}
        )

    # KCA-01: the app's trust file is the system CA file plus the test CA,
    # and each gateway copy keeps its system CAs and reads the test CA too.
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
        copies.append(
            {
                "pod": pod["metadata"]["name"],
                "ssl_cert_dir": env_of(container).get("SSL_CERT_DIR"),
                # Unset in the pod: the image's own SSL_CERT_FILE, its system CAs.
                "ssl_cert_file_overridden": "SSL_CERT_FILE" in env_of(container),
                "mounted": any(
                    m["name"] == "keeplane-extra-ca" and m["mountPath"] == EXTRA_DIR
                    for m in container.get("volumeMounts", [])
                ),
                "source": volumes.get("keeplane-extra-ca", {})
                .get("configMap", {})
                .get("name"),
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
            copy["ssl_cert_dir"] == EXTRA_DIR
            and not copy["ssl_cert_file_overridden"]
            and copy["mounted"]
            and copy["source"] == "cloud-provider-ca"
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
