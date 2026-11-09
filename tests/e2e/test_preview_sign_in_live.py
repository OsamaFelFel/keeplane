"""Spec 009 ST29 and ST30: CLI sign-in and the guarded gateway on the default preview.

Run against the Docker preview started by ``python3 deploy/local/up.py`` with
no flags (task 009-01, ADR 028). The suite signs a temporary developer in from
the source-tree CLI through the browser flow (the fixture browser uses the real
sign-in and consent pages) and the device flow, then sends requests through the
guarded gateway on port 5000 before and after one approved model is added.
Afterwards it signs the CLI out and removes what it created. See
preview-sign-in-live-cases.md.
"""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from http.client import HTTPException
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

import pytest

from tests.e2e import test_project_classes_live as classes
from tests.fixtures.class_runner import ClassRunner
from tests.fixtures.installed_cli_journey import HiddenFields, NoRedirects
from tests.support.client import BASE, RUNTIME, Browser
from tests.support.gateway import GATEWAY_SCRIPT, RESOURCE_PATH
from tests.support.reporting import report_path

pytestmark = [pytest.mark.live, pytest.mark.docker_only]

REPO = classes.REPO
REPORT = report_path("preview-sign-in-live.json")
CLI = REPO / "components/cli/keeplane.py"
GATEWAY = f"http://127.0.0.1:{classes.RUNTIME_PORT}/v1/chat/completions"
DIRECT = build_opener(ProxyHandler({}))
CASES = ("PSI-LIVE-01", "PSI-LIVE-02", "PSI-LIVE-03", "PSI-LIVE-04")


def enroller_reports():
    """The model enroller's reports since it started, oldest first."""
    logs = classes.compose(
        "--profile",
        "runtime",
        "logs",
        "--no-color",
        "--no-log-prefix",
        "model-enroller",
        runtime=True,
        timeout=60,
    )
    return [
        line.strip()
        for line in logs.stdout.splitlines()
        if line.strip().startswith(
            ("No model is enrolled", "Protected access is", "A model change is waiting")
        )
    ]


def settled(count):
    """The enroller's report once exactly `count` models are enrolled."""
    if not count:
        return ("No model is enrolled for protected access.",)
    noun = "model is" if count == 1 else "models are"
    return tuple(
        f"Protected access is {state}: {count} {noun} enrolled."
        for state in ("ready", "up to date")
    )


def wait_for_report(expected, timeout):
    """Wait until the enroller's latest report is one of `expected`.

    A removed or edited model holds the enroller for about 3 minutes and 16
    seconds (ADR 027), so a run straight after another waits that long.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reports = enroller_reports()
        if reports and reports[-1] in expected:
            return True
        time.sleep(1)
    return False


def unavailable_reason():
    reason = classes.unavailable_reason()
    if reason:
        return reason
    running = classes.compose(
        "--profile", "runtime", "ps", "-q", "model-enroller", runtime=True, timeout=30
    )
    if running.returncode or not running.stdout.split():
        return (
            "The model enroller is not running. Start the preview with "
            "`python3 deploy/local/up.py` (docs/guide/local-preview.md)."
        )
    return None


def guarded(token, project, model):
    """One request through the guarded gateway: (status or None, answer)."""
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
        with DIRECT.open(Request(GATEWAY, body, headers), timeout=60) as response:
            raw, status = response.read(8192), response.status
    except HTTPError as error:
        raw, status = error.read(8192), error.code
        error.close()
    except (URLError, HTTPException, OSError):
        return None, None
    try:
        answer = json.loads(raw)["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        answer = None
    return status, answer


class Cli:
    """The source-tree CLI, as a developer runs it, with a fixture browser."""

    def __init__(self, home, username, password):
        self.home = home
        login = home / "browser-login.json"
        login.write_text(
            json.dumps({"server": BASE, "username": username, "password": password})
        )
        login.chmod(0o600)
        driver = home / "browser.py"
        driver.write_text(
            "import sys\nfrom tests.fixtures.installed_cli_journey import browser\n"
            "try: browser(sys.argv[1])\nexcept Exception: raise SystemExit(1)\n"
        )
        self.env = {
            key: value for key, value in os.environ.items() if key in ("PATH", "LANG")
        }
        self.env.update(
            HOME=str(home),
            PYTHONUNBUFFERED="1",
            PYTHONPATH=str(REPO),
            BROWSER=shlex.join([sys.executable, str(driver), "%s"]),
            KEEPLANE_FIXTURE_LOGIN=str(login),
        )
        self.username, self.password = username, password

    def run(self, *arguments, timeout=90):
        result = subprocess.run(
            [sys.executable, str(CLI), *arguments],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def device_login(self, profile):
        """Start `login --device`, approve its code in the fixture browser, wait."""
        process = subprocess.Popen(
            [
                sys.executable,
                str(CLI),
                "login",
                "--device",
                "--server",
                BASE,
                "--profile",
                str(profile),
                "--timeout",
                "60",
            ],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            announcement = process.stdout.readline().strip()
            prefix = "Open " + BASE + "/oauth/confirm-device/ and enter code "
            assert announcement.startswith(prefix) and announcement.endswith(".")
            approved = self.approve_device(announcement[len(prefix) : -1])
            out, err = process.communicate(timeout=60)
            return process.returncode, approved, announcement, out.strip(), err.strip()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def approve_device(self, code):
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
                    Request(BASE + path, payload, headers), timeout=10
                )
            except HTTPError as error:
                response = error
            with response:
                assert response.status == expected, (path, response.status)
                return response.read(65536).decode(), response.headers

        raw, _ = request("/api/auth-options")
        request(
            "/api/session",
            {"username": self.username, "password": self.password},
            csrf=json.loads(raw)["csrf_token"],
        )
        page, _ = request("/oauth/confirm-device/?" + urlencode({"user_code": code}))
        fields = HiddenFields()
        fields.feed(page)
        fields.values["user_code"] = code
        _, headers = request("/oauth/confirm-device/", fields.values, expected=302)
        page, _ = request(headers["Location"])
        assert "Allow CLI access?" in page
        fields = HiddenFields()
        fields.feed(page)
        fields.values["action"] = "accept"
        page, _ = request("/oauth/confirm-device/", fields.values)
        return "CLI access allowed" in page


# `keeplane models` with no approved model: the documented empty catalog, exit 0
# (cli-project-commands.md: "an empty list is valid"), also on a fresh preview
# where no admin has saved a data-class or model setting yet.
def empty_catalog(listed, project):
    code, out, err = listed
    try:
        catalog = json.loads(out)
    except ValueError:
        return False
    # With nothing to list, nothing is marked as the current choice (Spec 004 ST17).
    return (
        code == 0
        and err == ""
        and catalog == {"project_id": project, "models": [], "chosen_by": None}
    )


def access_token(profile):
    return json.loads((profile / "credential.json").read_text())["access_token"]


def run_cases():
    suffix = uuid.uuid4().hex[:8]
    model, upstream = "psi-" + suffix, "psi-up-" + suffix
    project = str(uuid.uuid4())
    password = (RUNTIME / "first-admin-password").read_text().strip()
    developer_name = "sign-in-live-" + suffix
    developer_password = uuid.uuid4().hex + uuid.uuid4().hex
    cases, failures = [], []
    approved_before = []
    state = {"developer": None, "model": False}
    admin = Browser()

    def record(identifier, verdict, observed):
        cases.append({"id": identifier, "verdict": verdict, "observed": observed})

    with (
        tempfile.TemporaryDirectory(prefix="keeplane-sign-in-") as directory,
        ClassRunner([upstream], port=classes.RUNNER_PORT) as runner,
    ):
        home = Path(directory)
        browser_profile, device_profile = (
            home / "browser-account",
            home / "device-account",
        )
        cli = Cli(home, developer_name, developer_password)
        try:
            assert admin.login("first-admin", password)[0] == 200
            _, listing, _ = admin.fetch("/api/models")
            approved_before = sorted(
                row["id"] for row in listing["models"] if row.get("approved")
            )
            if not wait_for_report(settled(len(approved_before)), timeout=240):
                raise RuntimeError("The model enroller did not settle before the cases")
            status, user, _ = admin.fetch(
                "/api/users",
                {
                    "username": developer_name,
                    "role": "developer",
                    "password": developer_password,
                },
                method="POST",
            )
            if status != 201:
                raise RuntimeError(f"Creating the developer returned {status}")
            state["developer"] = user["id"]

            # PSI-LIVE-01: browser sign-in with the CLI's default settings.
            code, out, err = cli.run(
                "login",
                "--server",
                BASE,
                "--profile",
                str(browser_profile),
                "--timeout",
                "60",
            )
            who = cli.run("whoami", "--profile", str(browser_profile))
            mode = (browser_profile / "credential.json").stat().st_mode & 0o777
            record(
                "PSI-LIVE-01",
                "pass"
                if code == 0
                and out.endswith("Signed in to Keeplane.")
                and who[0] == 0
                and developer_name in who[1]
                and mode == 0o600
                else "fail",
                {
                    "login_exit": code,
                    "login_output": out.splitlines()[-1:],
                    "login_errors": bool(err),
                    "whoami_exit": who[0],
                    "whoami_names_developer": developer_name in who[1],
                    "credential_mode": oct(mode),
                },
            )

            # PSI-LIVE-02: device sign-in into a second profile.
            code, approved, announcement, out, err = cli.device_login(device_profile)
            who = cli.run("whoami", "--profile", str(device_profile))
            record(
                "PSI-LIVE-02",
                "pass"
                if code == 0
                and approved
                and out == "Signed in to Keeplane."
                and who[0] == 0
                and developer_name in who[1]
                else "fail",
                {
                    "login_exit": code,
                    "approved_in_browser": approved,
                    "announced_local_address": announcement.startswith("Open " + BASE),
                    "login_output": out,
                    "whoami_exit": who[0],
                },
            )

            token = access_token(browser_profile)
            registered = cli.run(
                "register-project",
                "--profile",
                str(browser_profile),
                "--project",
                project,
                "--name",
                "Sign-in live " + suffix,
            )
            if registered[0]:
                raise RuntimeError("Registering the project from the CLI failed")

            # PSI-LIVE-03: no approved model, nothing is served.
            if approved_before:
                record(
                    "PSI-LIVE-03",
                    "not-run",
                    {
                        "reason": "the preview already has approved models",
                        "approved": approved_before,
                    },
                )
            else:
                reports = enroller_reports()
                listed = cli.run(
                    "models", "--profile", str(browser_profile), "--project", project
                )
                before = runner.snapshot()
                answer = guarded(token, project, model)
                record(
                    "PSI-LIVE-03",
                    "pass"
                    if reports[-1:] == list(settled(0))
                    and answer[0] != 200
                    and runner.snapshot() == before
                    and empty_catalog(listed, project)
                    else "fail",
                    {
                        "enroller": reports[-1:],
                        "gateway_status": answer[0],
                        "models_exit": listed[0],
                        "models_output": listed[1],
                        "models_errors": listed[2],
                        "upstream_calls": runner.snapshot().get(upstream, 0),
                    },
                )

            # PSI-LIVE-04: one more approved model is enrolled and answers.
            status, result, _ = admin.fetch(
                "/api/models",
                {
                    "name": model,
                    "model": upstream,
                    "source": "runner",
                    "address": classes.RUNNER_ADDRESS,
                    "approved_classes": ["Public"],
                },
                method="POST",
            )
            if status != 200:
                raise RuntimeError(
                    f"Adding the fixture model returned {status}: {result}"
                )
            state["model"] = True
            ready = wait_for_report(settled(len(approved_before) + 1), timeout=90)
            listed = cli.run(
                "models", "--profile", str(browser_profile), "--project", project
            )
            before = runner.snapshot().get(upstream, 0)
            answered = guarded(token, project, model)
            middle = runner.snapshot().get(upstream, 0)
            anonymous = guarded(None, project, model)
            after = runner.snapshot().get(upstream, 0)
            record(
                "PSI-LIVE-04",
                "pass"
                if ready
                and listed[0] == 0
                and model in listed[1]
                and answered == (200, "class answer")
                and middle - before == 1
                and anonymous[0] in (401, 403)
                and after == middle
                else "fail",
                {
                    "enroller": enroller_reports()[-1:],
                    "models_lists_it": model in listed[1],
                    "signed_in": answered,
                    "signed_in_upstream_calls": middle - before,
                    "anonymous_status": anonymous[0],
                    "anonymous_upstream_calls": after - middle,
                },
            )
        finally:
            for profile in (browser_profile, device_profile):
                if (profile / "credential.json").exists():
                    code, _, _ = cli.run("logout", "--profile", str(profile))
                    if code:
                        failures.append(f"{profile.name} logout failed")
            restore(admin, password, model, state, failures)
            # Removing the model starts the enroller's ADR 027 wait. Return
            # only once it has settled again, so the next suite starts clean.
            if state["model"] and not wait_for_report(
                settled(len(approved_before)), timeout=300
            ):
                failures.append("the model enroller did not settle after clean-up")
    cleanup = "complete" if not failures else "; ".join(failures)
    report = {
        "suite": "Spec 009 ST29/ST30 CLI sign-in and the guarded gateway on the default preview",
        "time_utc": datetime.now(timezone.utc).isoformat(),
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


def restore(admin, password, model, state, failures):
    try:
        admin = Browser()
        if admin.login("first-admin", password)[0] != 200:
            raise RuntimeError("sign-in failed")
        if state["model"]:
            status, _, _ = admin.fetch(
                f"/api/models/{model}/setup", {}, method="DELETE"
            )
            if status not in (200, 404):
                failures.append(f"model setup removal returned {status}")
            removed = classes.compose(
                "exec",
                "-T",
                "app",
                "python",
                "-c",
                GATEWAY_SCRIPT,
                "DELETE",
                RESOURCE_PATH + "/" + model,
                "-",
                timeout=60,
            )
            if removed.returncode:
                failures.append("model gateway removal could not be confirmed")
        if state["developer"]:
            status, _, _ = admin.fetch(
                f"/api/users/{state['developer']}", {}, method="DELETE"
            )
            if status != 200:
                failures.append(f"developer removal returned {status}")
        admin.fetch("/sign-out", method="POST")
    except Exception as error:  # noqa: BLE001 - report, never hide, an incomplete restore.
        failures.append(f"restore raised {type(error).__name__}")


def test_preview_sign_in_live():
    reason = unavailable_reason()
    if reason:
        pytest.skip(reason)
    report = run_cases()
    assert [case["id"] for case in report["cases"]] == list(CASES)
    assert report["failed"] == 0 and report["cleanup"] == "complete"
    if report["not_run"]:
        pytest.skip(
            "Not run on this preview: "
            + ", ".join(report["not_run"])
            + " (needs a freshly started preview with no approved model)"
        )


if __name__ == "__main__":
    reason = unavailable_reason()
    if reason:
        print("Not run: " + reason)
        sys.exit(2)
    result = run_cases()
    sys.exit(int(bool(result["failed"]) or result["cleanup"] != "complete"))
