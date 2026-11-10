"""The protected developer path on Kubernetes: KDEV-01 to KDEV-04.

Runs against the protected developer release that
``KEEPLANE_KIND_PROTECTED=on deploy/local/kind-up.sh`` installs on the local
kind cluster (``deploy/local/kind_protected.py``): PostgreSQL accounts with CLI
sign-in, the managed gateway with the model enroller on both copies, and one
public HTTPS address, https://keeplane.kind.test, through an ingress
controller. Two temporary developers sign in from the source-tree CLI with the
device code, as on a machine with no browser, and run ``keeplane code`` with the
real pinned OpenCode 2.0.27 runtime through the public address: on a cloud
model with the organization's shared key, on their own key, and on an own key
the provider refuses (DEV-10 and DEV-09 of developer-journey-cases.md, on
Kubernetes). The provider is the release's HTTPS fixture provider, which
answers for api.openai.com inside the cluster. Afterwards it signs both CLIs
out and removes the models and developers. See kubernetes-developer-cases.md.

The runtime comes from ``KEEPLANE_OPENCODE_V2_BIN``. Without it KDEV-02 to
KDEV-04 are recorded as not run and the test is skipped, so CI fails. It
refuses any Kubernetes context but kind-keeplane and never prints a key.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

import pytest

from components.cli import browser_login, coding, device_login, project_identity
from tests.e2e import test_developer_journey as journey
from tests.e2e import test_preview_sign_in_live as preview
from tests.fixtures.installed_cli_journey import HiddenFields, NoRedirects
from tests.support.client import RUNTIME, Browser
from tests.support.kind_trial import CONTEXT, kind_kubeconfig
from tests.support.reporting import report_path

pytestmark = [pytest.mark.live, pytest.mark.kubernetes]

KUBECONFIG = kind_kubeconfig()
NAMESPACE = "keeplane-protected"
HOST = "keeplane.kind.test"
BASE = "https://" + HOST
GATEWAY = BASE + "/v1"
# The release's test CA (kind_protected.py): the public address's certificate.
CA = RUNTIME / "kind-protected/ca.pem"
REPORT = report_path("kind-protected.json")
CASES = ("KDEV-01", "KDEV-02", "KDEV-03", "KDEV-04")
# Two fixture-served OpenAI model names: one on the shared key, one on
# developers' own keys (each upstream model can be added once).
SHARED_UPSTREAM = "gpt-5-mini"
OWN_UPSTREAM = "gpt-4.1-mini"
DEVICE_PREFIX = "Open " + BASE + "/oauth/confirm-device/ and enter code "
COPIES = ("keeplane-gateway-0", "keeplane-gateway-1")


def kubectl(*args, data=None, timeout=120):
    return subprocess.run(
        ["kubectl", "--kubeconfig", KUBECONFIG, *args],
        input=data,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def unavailable_reason():
    try:
        context = kubectl("config", "current-context").stdout.strip()
    except OSError:
        return "kubectl is not installed"
    if context != CONTEXT:
        return f"The Kubernetes context is {context!r}, not {CONTEXT}"
    if not CA.is_file():
        return f"No protected release here: {CA} is missing. See docs/guide/kubernetes-local.md."
    ready = kubectl(
        "-n", NAMESPACE, "get", "statefulset", "keeplane-gateway",
        "-o", "jsonpath={.status.readyReplicas}",
    )  # fmt: skip
    if ready.returncode or ready.stdout.strip() != str(len(COPIES)):
        return "The protected release's gateway copies are not ready"
    return None


def enroller_reports(copy):
    """One copy's model enroller reports since it started, oldest first."""
    logs = kubectl("-n", NAMESPACE, "logs", copy, "-c", "model-enroller", timeout=60)
    return [
        line.strip()
        for line in logs.stdout.splitlines()
        if line.strip().startswith(
            ("No model is enrolled", "Protected access is", "A model change is waiting")
        )
    ]


def wait_for_enrollers(count, timeout):
    """Wait until every copy's enroller reports exactly `count` models enrolled."""
    expected = preview.settled(count)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        latest = [(enroller_reports(copy) or [None])[-1] for copy in COPIES]
        if all(report in expected for report in latest):
            return True
        time.sleep(2)
    return False


def fixture(script, *args):
    """Run Python in the release's fixture provider pod; its last line."""
    result = kubectl(
        "-n", NAMESPACE, "exec", "deploy/cloud-provider", "-c", "cloud-provider",
        "--", "python", "-c", script, *args,
    )  # fmt: skip
    return result.returncode, (result.stdout.strip().splitlines() or [""])[-1]


def cloud_state():
    """The fixture's record: answers and the key hashes it was sent, and the raw text."""
    code, raw = fixture(journey.CALLS_SCRIPT)
    try:
        data = json.loads(raw) if not code else None
    except ValueError:
        return {}, raw
    return (data if isinstance(data, dict) else {}), raw


def mark_key(key, verdict):
    code, out = fixture(journey.MARK_KEY_SCRIPT, journey.key_hash(key), verdict)
    if code or out != "marked":
        raise RuntimeError("Could not set the fixture provider's answer for a key")


def key_calls(state, key):
    return journey.key_calls(state, key)


class Developer:
    """A developer on a machine with no browser: own home, CLI and runtime."""

    def __init__(self, home, username, password, runtime):
        home.mkdir()
        self.home, self.username, self.password = home, username, password
        self.env = {
            key: value for key, value in os.environ.items() if key in ("PATH", "LANG")
        }
        self.env.update(
            HOME=str(home),
            PYTHONUNBUFFERED="1",
            PYTHONPATH=str(preview.REPO),
            # Over SSH with no display, `keeplane login` uses the device code.
            SSH_CONNECTION="203.0.113.7 50022 127.0.0.1 22",
            # The CLI trusts the release's test CA, as for a private CA.
            SSL_CERT_FILE=str(CA),
        )
        if runtime is not None:
            tools = home / "bin"
            tools.mkdir()
            (tools / "opencode").symlink_to(runtime)
            self.env["PATH"] = str(tools) + os.pathsep + self.env.get("PATH", "")

    def run(self, *arguments, cwd=None, timeout=300, stdin=None):
        result = subprocess.run(
            [sys.executable, str(preview.CLI), *arguments],
            env=self.env,
            cwd=cwd or self.home,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def saved(self):
        try:
            return json.loads(
                (self.home / ".config/keeplane/account/credential.json").read_text()
            )
        except (OSError, ValueError):
            return {}

    def login(self):
        """`keeplane login --server` with no browser, approved from another device."""
        process = subprocess.Popen(
            [
                sys.executable,
                str(preview.CLI),
                "login",
                "--server",
                BASE,
                "--timeout",
                "90",
            ],
            env=self.env,
            cwd=self.home,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            lines = [process.stdout.readline().strip() for _ in range(2)]
            found = re.search(re.escape(DEVICE_PREFIX) + r"(\S+)\.", lines[1])
            approved = found is not None and self.approve(found.group(1))
            out, err = process.communicate(timeout=120)
            return process.returncode, lines, approved, out.strip(), err.strip()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def approve(self, code):
        """Approve the device code on Keeplane's real pages, as this developer."""
        opener = build_opener(
            ProxyHandler({}), HTTPCookieProcessor(CookieJar()), NoRedirects()
        )

        def request(path, data=None, *, csrf=None, expected=200):
            headers = {"Origin": BASE}
            payload = None
            if csrf:
                headers.update(
                    {
                        "Content-Type": "application/json",
                        "X-CSRFToken": csrf,
                        "X-Keeplane-Action": "1",
                    }
                )
                payload = json.dumps(data).encode()
            elif data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                payload = urlencode(data).encode()
            try:
                response = opener.open(
                    Request(BASE + path, payload, headers), timeout=20
                )
            except HTTPError as error:
                response = error
            with response:
                if response.status != expected:
                    raise ValueError(f"{path} answered {response.status}")
                return response.read(65536).decode(), response.headers

        try:
            raw, _ = request("/api/auth-options")
            request(
                "/api/session",
                {"username": self.username, "password": self.password},
                csrf=json.loads(raw)["csrf_token"],
            )
            page, _ = request(
                "/oauth/confirm-device/?" + urlencode({"user_code": code})
            )
            fields = HiddenFields()
            fields.feed(page)
            fields.values["user_code"] = code
            _, headers = request("/oauth/confirm-device/", fields.values, expected=302)
            page, _ = request(headers["Location"])
            if "Allow CLI access?" not in page:
                return False
            fields = HiddenFields()
            fields.feed(page)
            fields.values["action"] = "accept"
            page, _ = request("/oauth/confirm-device/", fields.values)
            return "CLI access allowed" in page
        except (OSError, ValueError, KeyError):
            return False


def key_status(developer, cwd, model):
    code, out, _ = developer.run("keys", "list", cwd=cwd)
    try:
        row = next(row for row in json.loads(out)["models"] if row["id"] == model)
        return code, row["own_key_required"], row["status"]
    except (ValueError, KeyError, TypeError, StopIteration):
        return code, None, None


def save_own_key(developer, cwd, model):
    """A new key the provider accepts, saved with `keeplane keys set`."""
    key = "own-" + uuid.uuid4().hex + uuid.uuid4().hex
    mark_key(key, "accepted")
    before = key_status(developer, cwd, model)
    saved = developer.run(
        "keys", "set", "--model", model, "--key-stdin", cwd=cwd, stdin=key + "\n"
    )
    try:
        status = json.loads(saved[1] or "{}").get("status")
    except ValueError:
        status = None
    return key, before, saved[0], status


def run_cases():
    binary = journey.runtime_binary()
    suffix = uuid.uuid4().hex[:8]
    shared_model, own_model = "kdev-shared-" + suffix, "kdev-own-" + suffix
    remote = f"https://git.example.test/kdev/sample-{suffix}.git"
    project = project_identity.remote_project(remote).id
    password = (RUNTIME / "first-admin-password").read_text().strip()
    shared_key = (RUNTIME / "cloud-provider-key").read_text().strip()
    names = {"first": "kdev-first-" + suffix, "second": "kdev-second-" + suffix}
    secrets = {key: uuid.uuid4().hex + uuid.uuid4().hex for key in names}
    cases, failures = [], []
    state = {"users": [], "models": []}
    admin = Browser(BASE)

    def record(identifier, verdict, observed):
        cases.append({"id": identifier, "verdict": verdict, "observed": observed})

    def not_run(identifier):
        record(
            identifier,
            "not-run",
            {"reason": "KEEPLANE_OPENCODE_V2_BIN does not name the pinned runtime"},
        )

    with tempfile.TemporaryDirectory(prefix="keeplane-kdev-") as directory:
        root = Path(directory)
        first = Developer(root / "first", names["first"], secrets["first"], binary)
        second = Developer(root / "second", names["second"], secrets["second"], binary)
        repo = journey.sample_repo(root / "first/sample", remote)
        clone = journey.sample_repo(root / "second/sample", remote)
        try:
            if admin.login("first-admin", password)[0] != 200:
                raise RuntimeError("The first admin could not sign in")
            _, listing, _ = admin.fetch("/api/models")
            approved_before = sum(
                bool(row.get("approved")) for row in listing["models"]
            )
            for key in ("first", "second"):
                status, user, _ = admin.fetch(
                    "/api/users",
                    {
                        "username": names[key],
                        "role": "developer",
                        "password": secrets[key],
                    },
                    method="POST",
                )
                if status != 201:
                    raise RuntimeError(f"Creating a developer returned {status}")
                state["users"].append(user["id"])
            for payload in (
                {
                    "name": shared_model,
                    "model": SHARED_UPSTREAM,
                    "source": "openai",
                    "key_choice": "shared",
                    "shared_key": shared_key,
                    "approved_classes": ["Public"],
                },
                {
                    "name": own_model,
                    "model": OWN_UPSTREAM,
                    "source": "openai",
                    "key_choice": "personal",
                    "approved_classes": ["Public"],
                },
            ):
                status, result, _ = admin.fetch("/api/models", payload, method="POST")
                if status != 200:
                    raise RuntimeError(
                        f"Adding {payload['name']} returned {status}: {result}"
                    )
                state["models"].append(payload["name"])
            # Both copies' enrollers confirm the two models before any call.
            enrolled = wait_for_enrollers(approved_before + 2, timeout=300)
            if not enrolled:
                raise RuntimeError("The model enrollers did not enrol the two models")

            # KDEV-01: device sign-in through the public address; the server
            # gives the CLI its gateway address, which the CLI saves.
            code, lines, approved, out, err = first.login()
            who = first.run("whoami")
            saved = first.saved()
            record(
                "KDEV-01",
                "pass"
                if code == 0
                and lines[0] == browser_login.NO_BROWSER
                and lines[1].startswith(DEVICE_PREFIX)
                and approved
                and out == "Signed in to Keeplane."
                and who[0] == 0
                and names["first"] in who[1]
                and saved.get("client_id") == device_login.CLIENT_ID
                and saved.get("issuer") == BASE
                and saved.get("gateway") == GATEWAY
                else "fail",
                {
                    "login_exit": code,
                    "first_line": lines[0],
                    "code_shown": lines[1].startswith(DEVICE_PREFIX),
                    "approved_elsewhere": approved,
                    "login_output": out,
                    "login_errors": bool(err),
                    "whoami_exit": who[0],
                    "whoami_output": who[1],
                    "sign_in_client": saved.get("client_id"),
                    "server": saved.get("issuer"),
                    "saved_gateway": saved.get("gateway"),
                },
            )

            # KDEV-02: a protected model answers through the public address:
            # `keeplane code` on the shared-key model with the saved gateway,
            # and one request with the developer's sign-in; none without it.
            listed = first.run("models", cwd=repo)
            try:
                shown = {row["id"] for row in json.loads(listed[1])["models"]}
            except (ValueError, KeyError, TypeError):
                shown = set()
            anonymous = preview.guarded(
                None, project, shared_model, GATEWAY + "/chat/completions"
            )
            direct = preview.guarded(
                saved.get("access_token"),
                project,
                shared_model,
                GATEWAY + "/chat/completions",
            )
            if binary is None:
                not_run("KDEV-02")
            else:
                before, _ = cloud_state()
                task = first.run("code", "--model", shared_model, "Say hello", cwd=repo)
                after, raw = cloud_state()
                answered = (
                    key_calls(after, shared_key)[0] - key_calls(before, shared_key)[0]
                )
                record(
                    "KDEV-02",
                    "pass"
                    if listed[0] == 0
                    and {shared_model, own_model} <= shown
                    and anonymous[0] in (401, 403)
                    and anonymous[1] is None
                    and direct == (200, "mock cloud answer")
                    and task[0] == 0
                    and "mock cloud answer" in task[1]
                    and coding.ANSWERED_BY.format(models=shared_model) in task[2]
                    and answered >= 1
                    and shared_key not in raw
                    else "fail",
                    {
                        "models_exit": listed[0],
                        "both_models_listed": {shared_model, own_model} <= shown,
                        "without_sign_in": anonymous[0],
                        "with_sign_in": direct[0],
                        "direct_answer": direct[1],
                        "code_exit": task[0],
                        "answer_shown": "mock cloud answer" in task[1],
                        "cli_messages": [
                            line for line in task[2].splitlines() if line.strip()
                        ],
                        "shared_key_answers": answered,
                        "runtime_errors": task[1].splitlines()[-3:] if task[0] else [],
                    },
                )

            # KDEV-03 (DEV-10 on Kubernetes): a task on the developer's own key.
            if binary is None:
                not_run("KDEV-03")
            else:
                key, listed_before, set_exit, set_status = save_own_key(
                    first, repo, own_model
                )
                sign_ins = [
                    n for n in journey.RUNTIME_SIGN_INS if (first.home / n).exists()
                ]
                before, _ = cloud_state()
                task = first.run("code", "--model", own_model, "Say hello", cwd=repo)
                after, raw = cloud_state()
                sign_ins += [
                    n for n in journey.RUNTIME_SIGN_INS if (first.home / n).exists()
                ]
                listed = key_status(first, repo, own_model)
                own = [
                    a - b for a, b in zip(key_calls(after, key), key_calls(before, key))
                ]
                shared = [
                    a - b
                    for a, b in zip(
                        key_calls(after, shared_key), key_calls(before, shared_key)
                    )
                ]
                others = sorted(
                    digest
                    for digest, seen in after.get("keys", {}).items()
                    if digest != journey.key_hash(key)
                    and seen != before.get("keys", {}).get(digest)
                )
                answers = after.get("count", 0) - before.get("count", 0)
                record(
                    "KDEV-03",
                    "pass"
                    if listed_before[1:] == (True, "missing")
                    and set_exit == 0
                    and set_status == "added"
                    and task[0] == 0
                    and "mock cloud answer" in task[1]
                    and coding.ANSWERED_BY.format(models=own_model) in task[2]
                    and own[0] >= 1
                    and own[1] == 0
                    and answers == own[0]
                    and shared == [0, 0]
                    and not others
                    and not sign_ins
                    and listed == (0, True, "added")
                    and key not in raw
                    and key not in task[1] + task[2]
                    else "fail",
                    {
                        "status_before": listed_before[2],
                        "set_exit": set_exit,
                        "set_status": set_status,
                        "code_exit": task[0],
                        "answer_shown": "mock cloud answer" in task[1],
                        "cli_messages": [
                            line for line in task[2].splitlines() if line.strip()
                        ],
                        "provider_answers": answers,
                        "own_key_requests": dict(zip(("accepted", "refused"), own)),
                        "shared_key_requests": dict(
                            zip(("accepted", "refused"), shared)
                        ),
                        "other_keys_seen": len(others),
                        "runtime_sign_ins": sign_ins,
                        "keys_list": dict(
                            zip(("exit", "own_key_required", "status"), listed)
                        ),
                        "runtime_errors": task[1].splitlines()[-3:] if task[0] else [],
                    },
                )

            # KDEV-04 (DEV-09 on Kubernetes): the provider refuses the second
            # developer's own key during a task, which stops with exit 1.
            if binary is None:
                not_run("KDEV-04")
            else:
                signed_in = second.login()
                key, listed_before, set_exit, set_status = save_own_key(
                    second, clone, own_model
                )
                mark_key(key, "refused")
                before, _ = cloud_state()
                task = second.run("code", "--model", own_model, "Say hello", cwd=clone)
                after, raw = cloud_state()
                listed = key_status(second, clone, own_model)
                message = coding.KEY_REFUSED.format(model=own_model)
                accepted = key_calls(after, key)[0] - key_calls(before, key)[0]
                refused = key_calls(after, key)[1] - key_calls(before, key)[1]
                record(
                    "KDEV-04",
                    "pass"
                    if signed_in[0] == 0
                    and signed_in[2]
                    and listed_before[1:] == (True, "missing")
                    and set_exit == 0
                    and set_status == "added"
                    and task[0] == 1
                    and message in task[2]
                    and coding.ANSWERED_BY.format(models=own_model) not in task[2]
                    and listed == (0, True, "refused")
                    and accepted == 0
                    and refused >= 1
                    and key not in raw
                    and key not in task[1] + task[2]
                    else "fail",
                    {
                        "login_exit": signed_in[0],
                        "status_before": listed_before[2],
                        "set_exit": set_exit,
                        "set_status": set_status,
                        "code_exit": task[0],
                        "refused_message_shown": message in task[2],
                        "cli_messages": [
                            line for line in task[2].splitlines() if line.strip()
                        ],
                        "keys_list": dict(
                            zip(("exit", "own_key_required", "status"), listed)
                        ),
                        "provider_accepted_key": accepted,
                        "provider_refused_key": refused,
                        "key_in_output": key in raw or key in task[1] + task[2],
                    },
                )
        finally:
            for developer in (first, second):
                if developer.saved() and developer.run("logout")[0]:
                    failures.append(f"{developer.username} logout failed")
            restore(admin, password, state, failures)
    cleanup = "complete" if not failures else "; ".join(failures)
    report = {
        "suite": "Protected developer path on the kind cluster, KDEV-01 to KDEV-04",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "address": BASE,
        "runtime": "OpenCode 2.0.27 (pinned)" if binary else None,
        "cases": cases,
        "cleanup": cleanup,
        "passed": sum(case["verdict"] == "pass" for case in cases),
        "failed": sum(case["verdict"] == "fail" for case in cases),
        "not_run": [case["id"] for case in cases if case["verdict"] == "not-run"],
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"{report['passed']} passed, {report['failed']} failed; cleanup {cleanup}; {REPORT}"
    )
    for case in cases:
        print(case["id"], case["verdict"], json.dumps(case["observed"]))
    return report


def restore(admin, password, state, failures):
    """Remove the models and developers; the namespace starts fresh on the next start."""
    try:
        browser = Browser(BASE)
        if browser.login("first-admin", password)[0] != 200:
            raise RuntimeError("sign-in failed")
        for model in state["models"]:
            status, _, _ = browser.fetch(
                f"/api/models/{model}/setup", {}, method="DELETE"
            )
            if status not in (200, 404):
                failures.append(f"{model} setup removal returned {status}")
        for user in state["users"]:
            status, _, _ = browser.fetch(f"/api/users/{user}", {}, method="DELETE")
            if status != 200:
                failures.append(f"developer removal returned {status}")
        browser.fetch("/sign-out", method="POST")
        admin.fetch("/sign-out", method="POST")
    except Exception as error:  # noqa: BLE001 - report, never hide, an incomplete restore.
        failures.append(f"restore raised {type(error).__name__}")


def test_kind_protected():
    # Every HTTPS call to the release trusts its test CA, as the CLI's do.
    with patch.dict(os.environ, {"SSL_CERT_FILE": str(CA)}):
        reason = unavailable_reason()
        if reason:
            pytest.skip(reason)
        report = run_cases()
    assert [case["id"] for case in report["cases"]] == list(CASES)
    assert report["failed"] == 0 and report["cleanup"] == "complete"
    if report["not_run"]:
        pytest.skip("Not run: " + ", ".join(report["not_run"]))


if __name__ == "__main__":
    os.environ["SSL_CERT_FILE"] = str(CA)
    reason = unavailable_reason()
    if reason:
        print("Not run: " + reason)
        sys.exit(2)
    result = run_cases()
    sys.exit(int(bool(result["failed"]) or result["cleanup"] != "complete"))
