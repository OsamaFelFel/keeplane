"""The protected developer release on the isolated network: ISO-13 to ISO-20.

Runs in the isolated-network job of the Kubernetes live checks workflow,
after test_kubernetes_isolated.py has closed the network (ISO-02) and
restarted the node from the internal registry (ISO-11). The release is the
PostgreSQL install with CLI sign-in and the model enroller on both gateway
copies (deploy/local/protected-values.yaml with
tests/fixtures/isolated-network/protected-values.yaml), which
tests/fixtures/isolated-network/protected.py installed in namespace
keeplane-protected while the registry was still reachable. Its one public
address is https://keeplane-protected.isolated.test, through the ingress
controller; its model provider is the HTTPS provider fixture on the runner,
outside the cluster, which the cluster DNS gives the name api.openai.com.

The runner plays a developer's machine outside the cluster: the source-tree
CLI signs in through the browser flow (a fixture browser on the real sign-in
and consent pages) and the device flow, and sends protected model calls to
the public address with its sign-in. The cases then probe what the app and a
gateway copy (with its model enroller) can reach, restart the node with the
network still closed and check it all again. See kubernetes-isolated-cases.md.

They refuse any kubeconfig context other than kind-keeplane-isolated and
never print a key or password. No case is skipped: anything missing fails.
"""

import hashlib
import json
import os
import ssl
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

import pytest

from tests.e2e import test_kubernetes_isolated as iso
from tests.e2e import test_preview_sign_in_live as preview
from tests.support.client import Browser

pytestmark = [pytest.mark.live, pytest.mark.kubernetes]

NAMESPACE = "keeplane-protected"
HOST = "keeplane-protected.isolated.test"
BASE = "https://" + HOST
GATEWAY = BASE + "/v1"
# The run's CA: it signed the public address's and the provider's certificates.
CA = iso.RUNTIME / "ca.crt"
COPIES = ("keeplane-gateway-0", "keeplane-gateway-1")
# The provider fixture on the runner (protected.py, the workflow), by address.
PROVIDER = "172.30.0.1"
PROVIDER_NAME = "api.openai.com"
UPSTREAM = "gpt-5-mini"

# What the protected release's pods may reach (protected-values.yaml) ...
MODEL_PROVIDER = {"name": "model_provider", "host": PROVIDER, "port": 443}
ACCOUNT_DB = {
    "name": "account_database",
    "host": f"db.{NAMESPACE}.svc.cluster.local",
    "port": 5432,
}
GATEWAY_DB = {
    "name": "gateway_database",
    "host": f"postgres.{NAMESPACE}.svc.cluster.local",
    "port": 5432,
}
OWN_GATEWAY = {
    "name": "gateway",
    "host": f"keeplane.{NAMESPACE}.svc.cluster.local",
    "port": 4000,
}
OWN_APP = {
    "name": "app",
    "host": f"keeplane-app.{NAMESPACE}.svc.cluster.local",
    "port": 3000,
}
PROTECTED_PORT = {
    "name": "protected_port",
    "host": f"keeplane-gateway-runtime.{NAMESPACE}.svc.cluster.local",
    "port": 5000,
}
# ... and places on the same network it may not: the local-trial release's
# provider port on the same runner address and its fixture model, a team's
# own service, the internet and the registry.
TRIAL_PROVIDER = {"name": "trial_provider_port", "host": PROVIDER, "port": 18082}
TRIAL_MODEL = {
    "name": "trial_model",
    "host": "model.keeplane.svc.cluster.local",
    "port": 18080,
}


def kubectl(*args, timeout=300):
    return iso.kubectl(*args, timeout=timeout)


def context():
    return ssl.create_default_context(cafile=str(CA))


def opener():
    return build_opener(ProxyHandler({}), HTTPSHandler(context=context()))


def key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def provider_calls(key):
    """The requests the provider fixture accepted with this key (by its hash)."""
    with opener().open(f"https://{PROVIDER}/calls", timeout=15) as response:
        state = json.load(response)
    return state.get("keys", {}).get(key_hash(key), {}).get("accepted", 0)


def ready_page():
    try:
        with opener().open(BASE + "/health/ready", timeout=15) as response:
            return response.status
    except HTTPError as error:
        return error.code
    except OSError as error:
        return type(error).__name__


def protected_call(token, project, model):
    """One request to the public model path: (status or None, answer)."""
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 8,
        }
    ).encode()
    headers = {"Content-Type": "application/json", "X-Keeplane-Project-ID": project}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with opener().open(
            Request(GATEWAY + "/chat/completions", body, headers), timeout=60
        ) as response:
            raw, status = response.read(8192), response.status
    except HTTPError as error:
        raw, status = error.read(8192), error.code
        error.close()
    except OSError:
        return None, None
    try:
        answer = json.loads(raw)["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        answer = None
    return status, answer


def release_pods():
    return iso.pods(NAMESPACE)


def wait_for_release(since="", timeout=600):
    """Wait until every pod of the release runs containers started after
    `since` and is ready, with both app replicas and both gateway copies."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            found = release_pods()
            state = {
                p["metadata"]["name"]: iso.ready(p)
                and all(
                    c.get("state", {}).get("running", {}).get("startedAt", "") >= since
                    for c in p["status"].get("containerStatuses", [{}])
                )
                for p in found
            }
            names = list(state)
            done = (
                all(state.values())
                and sum(n.startswith("keeplane-app-") for n in names) == 2
                and all(copy in names for copy in COPIES)
            )
        except RuntimeError as error:
            state, done = {"error": str(error)[:200]}, False
        if done or time.monotonic() > deadline:
            return done, state
        time.sleep(10)


def enroller_reports(copy):
    """One copy's model enroller reports since it started, oldest first."""
    try:
        logs = kubectl("-n", NAMESPACE, "logs", copy, "-c", "model-enroller")
    except RuntimeError:
        return []
    return [
        line.strip()
        for line in logs.splitlines()
        if line.strip().startswith(
            ("No model is enrolled", "Protected access is", "A model change is waiting")
        )
    ]


def wait_for_enrollers(count, timeout=300):
    """Each copy's latest enroller report, once both report `count` models."""
    expected = preview.settled(count)
    deadline = time.monotonic() + timeout
    while True:
        latest = {copy: (enroller_reports(copy) or [None])[-1] for copy in COPIES}
        if all(report in expected for report in latest.values()):
            return True, latest
        if time.monotonic() > deadline:
            return False, latest
        time.sleep(3)


def developer_cli(home, username, password):
    """The source-tree CLI on the runner, trusting the run's CA."""
    home.mkdir()
    cli = preview.Cli(home, username, password, server=BASE)
    cli.env["SSL_CERT_FILE"] = str(CA)
    return cli


def saved(profile):
    try:
        return json.loads((profile / "credential.json").read_text())
    except (OSError, ValueError):
        return {}


def listed_models(cli, profile, project):
    code, out, _ = cli.run("models", "--profile", str(profile), "--project", project)
    try:
        return code, {row["id"] for row in json.loads(out)["models"]}
    except (ValueError, KeyError, TypeError):
        return code, set()


def egress():
    """What the protected app and gateway copy 0 (with its enroller) reach."""
    registry = iso.registry_target()
    blocked_for_both = [
        TRIAL_PROVIDER,
        TRIAL_MODEL,
        iso.INSIDE,
        iso.INTERNET,
        registry,
    ]
    app = iso.probe(
        "protected_app",
        [MODEL_PROVIDER, ACCOUNT_DB, OWN_GATEWAY, GATEWAY_DB, *blocked_for_both],
    )
    gateway = iso.probe_gateway(
        [MODEL_PROVIDER, ACCOUNT_DB, GATEWAY_DB, OWN_APP, *blocked_for_both],
        namespace=NAMESPACE,
    )
    names = iso.lookup(
        "protected_app", [PROVIDER_NAME, iso.REGISTRY_HOST, ACCOUNT_DB["host"]]
    )
    outside = [t["name"] for t in blocked_for_both]
    passed = (
        all(app[n] == "open" for n in ("model_provider", "account_database", "gateway"))
        and iso.blocked(app, "gateway_database", *outside)
        and all(
            gateway[n] == "open"
            for n in ("model_provider", "account_database", "gateway_database", "app")
        )
        and iso.blocked(gateway, *outside)
        and names.get(PROVIDER_NAME) == "resolved:" + PROVIDER
        and iso.unresolved(names, iso.REGISTRY_HOST)
        and iso.resolved(names, ACCOUNT_DB["host"])
    )
    return passed, {"app": app, "gateway_copy_0": gateway, "app_lookups": names}


def run_cases():
    current = kubectl("config", "current-context").strip()
    if current != iso.CONTEXT:
        raise SystemExit(
            f"Refusing Kubernetes context {current!r}; expected {iso.CONTEXT}"
        )
    results = []
    state = {"profiles": []}
    suffix = uuid.uuid4().hex[:8]
    model = "iso-protected-" + suffix
    project = str(uuid.uuid4())
    admin_password = (iso.RUNTIME / "first-admin-password").read_text().strip()
    shared_key = (iso.RUNTIME / "cloud-provider-key").read_text().strip()
    developer = "iso-developer-" + suffix
    developer_password = uuid.uuid4().hex + uuid.uuid4().hex

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

    def iso_13():
        # The network is still closed: the node can't reach the registry and
        # the visitor can't reach the internet.
        reaches, code = iso.node_reaches_registry()
        visitor = iso.probe("visitor", [iso.INTERNET])
        ready, pods = wait_for_release()
        images = {}
        for pod in release_pods():
            spec = pod["spec"]
            for container in spec.get("initContainers", []) + spec["containers"]:
                images[container["image"]] = container.get("imagePullPolicy")
        app_image = os.environ.get("KEEPLANE_ISOLATED_PROTECTED_IMAGE", "")
        pinned = all("@sha256:" in image for image in images)
        mirrored = json.loads(iso.MIRRORED.read_text())
        held = {(e["path"], e["digest"]) for e in mirrored}
        missing = sorted(
            ref
            for ref in images
            if (key := iso.mirror_key(ref)) is None
            or (iso.MIRROR_TOOL.mirror_path(key[0], key[1]), key[2]) not in held
        )
        page = ready_page()
        return (
            not reaches
            and iso.blocked(visitor, "internet")
            and ready
            and pinned
            and app_image.startswith(iso.MIRROR + "/")
            and app_image in images
            and not missing
            and page == 200,
            {
                "node_registry_status": code,
                "visitor": visitor,
                "pods_ready": pods,
                "images": images,
                "not_in_internal_registry": missing,
                "public_ready_check": page,
            },
        )

    def iso_14():
        admin = Browser(BASE)
        if admin.login("first-admin", admin_password)[0] != 200:
            raise RuntimeError("The first admin could not sign in")
        state["admin"] = admin
        _, listing, _ = admin.fetch("/api/models")
        state["approved_before"] = sum(
            bool(row.get("approved")) for row in listing["models"]
        )
        status, _, _ = admin.fetch(
            "/api/users",
            {
                "username": developer,
                "role": "developer",
                "password": developer_password,
            },
            method="POST",
        )
        if status != 201:
            raise RuntimeError(f"Creating the developer returned {status}")
        before = provider_calls(shared_key)
        added, result, _ = admin.fetch(
            "/api/models",
            {
                "name": model,
                "model": UPSTREAM,
                "source": "openai",
                "key_choice": "shared",
                "shared_key": shared_key,
                "approved_classes": ["Public"],
            },
            method="POST",
        )
        checked = provider_calls(shared_key) - before
        enrolled, reports = wait_for_enrollers(state["approved_before"] + 1)
        _, listing, _ = admin.fetch("/api/models")
        row = next((m for m in listing["models"] if m["id"] == model), {})
        return (
            added == 200
            and checked >= 1
            and row.get("approved")
            and row.get("kind") == "cloud"
            and enrolled,
            {
                "add_status": added,
                "add_error": (result or {}).get("error"),
                "provider_key_checks": checked,
                "listed": {k: row.get(k) for k in ("id", "kind", "approved")},
                "enroller_reports": reports,
            },
        )

    with tempfile.TemporaryDirectory(prefix="keeplane-iso-protected-") as directory:
        root = Path(directory)
        cli = developer_cli(root / "developer", developer, developer_password)
        browser_profile = root / "developer/browser-account"
        device_profile = root / "developer/device-account"
        state["profiles"] += [browser_profile, device_profile]

        def iso_15():
            code, out, err = cli.run(
                "login", "--server", BASE, "--profile", str(browser_profile),
                "--timeout", "60",
            )  # fmt: skip
            who = cli.run("whoami", "--profile", str(browser_profile))
            credential = saved(browser_profile)
            return (
                code == 0
                and out.endswith("Signed in to Keeplane.")
                and who[0] == 0
                and developer in who[1]
                and credential.get("issuer") == BASE
                and credential.get("gateway") == GATEWAY,
                {
                    "login_exit": code,
                    "login_output": out.splitlines()[-1:],
                    "login_errors": bool(err),
                    "whoami_exit": who[0],
                    "whoami_names_developer": developer in who[1],
                    "server": credential.get("issuer"),
                    "saved_gateway": credential.get("gateway"),
                },
            )

        def device_sign_in(profile):
            code, approved, announcement, out, err = cli.device_login(profile)
            who = cli.run("whoami", "--profile", str(profile))
            credential = saved(profile)
            return (
                code == 0
                and approved
                and announcement.startswith("Open " + BASE + "/oauth/confirm-device/")
                and out == "Signed in to Keeplane."
                and who[0] == 0
                and developer in who[1]
                and credential.get("gateway") == GATEWAY,
                {
                    "login_exit": code,
                    "approved_on_another_device": approved,
                    "code_shown_for_public_address": announcement.startswith(
                        "Open " + BASE
                    ),
                    "login_output": out,
                    "login_errors": bool(err),
                    "whoami_exit": who[0],
                    "saved_gateway": credential.get("gateway"),
                },
            )

        def iso_16():
            return device_sign_in(device_profile)

        def answers(profiles):
            """Each profile's protected call, and one without a sign-in."""
            before = provider_calls(shared_key)
            signed_in = {
                p.name: protected_call(saved(p).get("access_token"), project, model)
                for p in profiles
            }
            middle = provider_calls(shared_key)
            anonymous = protected_call(None, project, model)
            after = provider_calls(shared_key)
            passed = (
                all(v == (200, "mock cloud answer") for v in signed_in.values())
                and middle - before >= len(profiles)
                and anonymous[0] in (401, 403)
                and anonymous[1] is None
                and after == middle
            )
            return passed, {
                "signed_in": signed_in,
                "provider_answers": middle - before,
                "without_sign_in": anonymous[0],
                "provider_answers_without_sign_in": after - middle,
            }

        def iso_17():
            registered = cli.run(
                "register-project", "--profile", str(browser_profile),
                "--project", project, "--name", "Isolated protected " + suffix,
            )  # fmt: skip
            listed = listed_models(cli, browser_profile, project)
            passed, observed = answers([browser_profile, device_profile])
            observed.update(
                register_exit=registered[0],
                models_exit=listed[0],
                model_listed=model in listed[1],
            )
            return (
                passed and registered[0] == 0 and listed[0] == 0 and model in listed[1],
                observed,
            )

        def iso_18():
            return egress()

        def iso_19():
            targets = [OWN_APP, OWN_GATEWAY, PROTECTED_PORT]
            visitor = iso.probe("visitor", [*targets, iso.IN_CLUSTER_MODEL])
            neighbour = iso.probe("model", targets)
            names = [t["name"] for t in targets]
            return (
                iso.blocked(visitor, *names)
                and iso.blocked(neighbour, *names)
                and visitor["in_cluster_model"] == "open:200",
                {
                    "visitor_in_inside": visitor,
                    "trial_model_pod_in_keeplane": neighbour,
                },
            )

        def iso_20():
            since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            iso.run("docker", "restart", iso.NODE, timeout=180)
            iso.wait_for_node()
            ready, pods = wait_for_release(since)
            enrolled, reports = wait_for_enrollers(state["approved_before"] + 1)
            page = ready_page()
            reaches, code = iso.node_reaches_registry()
            still = cli.run("whoami", "--profile", str(browser_profile))
            again = root / "developer/device-after-restart"
            state["profiles"].append(again)
            signed, device = device_sign_in(again)
            answered, calls = answers([browser_profile, again])
            limited, probes = egress()
            return (
                ready
                and enrolled
                and page == 200
                and not reaches
                and still[0] == 0
                and developer in still[1]
                and signed
                and answered
                and limited,
                {
                    "pods_restarted_and_ready": pods,
                    "enroller_reports": reports,
                    "public_ready_check": page,
                    "node_registry_status": code,
                    "earlier_sign_in_still_works": still[0] == 0
                    and developer in still[1],
                    "device_sign_in": device,
                    "protected_calls": calls,
                    "reach": probes,
                },
            )

        try:
            for identifier, step in (
                ("ISO-13", iso_13),
                ("ISO-14", iso_14),
                ("ISO-15", iso_15),
                ("ISO-16", iso_16),
                ("ISO-17", iso_17),
                ("ISO-18", iso_18),
                ("ISO-19", iso_19),
                ("ISO-20", iso_20),
            ):
                case(identifier, step)
        finally:
            failures = []
            for profile in state["profiles"]:
                signed_in = (profile / "credential.json").exists()
                if signed_in and cli.run("logout", "--profile", str(profile))[0]:
                    failures.append(f"{profile.name} logout failed")
            if "admin" in state:
                try:
                    state["admin"].fetch("/sign-out", method="POST")
                except Exception:  # noqa: BLE001 - the cluster is disposable.
                    failures.append("admin sign-out raised")

    print(
        json.dumps(
            {
                "suite": "Keeplane's protected developer release on an isolated network",
                "results": results,
                "cleanup": "complete" if not failures else "; ".join(failures),
            },
            indent=2,
        )
    )
    return 1 if failures or any(r["verdict"] == "fail" for r in results) else 0


def test_kubernetes_isolated_protected(monkeypatch, report_file, capsys):
    monkeypatch.setattr("sys.argv", [__file__])
    # Every HTTPS call trusts the run's CA, as the developer's CLI does.
    with patch.dict(os.environ, {"SSL_CERT_FILE": str(CA)}):
        status = run_cases()
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    assert status == 0
    verify_cases(__file__, output.out, report_file)
