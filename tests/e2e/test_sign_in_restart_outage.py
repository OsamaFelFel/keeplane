"""Task 009-15: CLI sign-in, refresh and coding through restarts and outages.

Cases: tests/e2e/sign-in-restart-outage-cases.md (SRO-01 to SRO-17). A
disposable PostgreSQL install of its own (tests/fixtures/sign_in_outage.py),
on ports the system picks, so the local preview is never touched. The
source-tree CLI signs in through Keeplane's real browser and device pages,
refreshes, and codes through a customer-run gateway that asks Keeplane's
route check before every model call, while the app, PostgreSQL or the
gateway restarts or is down.
"""

import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from components.cli import browser_login, coding, credential_refresh, sign_in_again
from tests.fixtures.sign_in_outage import MODEL, Stack, approve_device

pytestmark = [pytest.mark.live, pytest.mark.infrastructure]

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "components/cli/keeplane.py"
RUNTIME = ROOT / "tests/fixtures/outage_runtime.py"
APP_IMAGE = os.environ.get(
    "KEEPLANE_SIGN_IN_POSTGRES_IMAGE", "keeplane-preview:postgres-cli-auth-local"
)
DIRECT = build_opener(ProxyHandler({}))
REPORT = {}

UNAVAILABLE = browser_login.UNAVAILABLE + "\n"
REFRESH_UNAVAILABLE = credential_refresh.UNAVAILABLE + "\n"
EXPIRED_READ = sign_in_again.EXPIRED_READ + "\n"
EXPIRED_CODE = (
    "Your Keeplane sign-in has expired, so nothing was sent. "
    "Run `keeplane login` to sign in again.\n"
)
SERVER_DOWN_MORE = coding.SERVER_DOWN.format(more="more ")
GATEWAY_DOWN_MORE = coding.GATEWAY_DOWN.format(more="more ")
START_UNAVAILABLE = coding.START_UNAVAILABLE + "\n"
GATEWAY_DOWN_AT_START = coding.GATEWAY_DOWN.format(more="") + "\n"
NOT_RECORDED = "couldn't record this task's usage"


def unavailable_reason():
    try:
        found = subprocess.run(
            ["docker", "image", "inspect", APP_IMAGE],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "Docker is not available"
    if found.returncode:
        return (
            f"Build {APP_IMAGE} first: docker build --target postgres-cli-auth-trial "
            f"-t {APP_IMAGE} -f components/control-plane/Dockerfile ."
        )
    return None


class Developer:
    """One developer's machine: a private home, the source-tree CLI and a repo."""

    def __init__(self, stack, home, username, password):
        self.stack, self.home = stack, home
        self.username, self.password = username, password
        self.control = home / "control"
        self.control.mkdir()
        self.login_file = home / "browser-login.json"
        self.stops([])
        driver = home / "browser.py"
        driver.write_text(
            "import sys\nfrom tests.fixtures.sign_in_outage import browser\n"
            "try: browser(sys.argv[1])\nexcept Exception: raise SystemExit(1)\n"
        )
        runtime = home / "opencode"
        runtime.write_text(
            "#!/bin/sh\nexec "
            + shlex.join([sys.executable, str(RUNTIME), str(self.control)])
            + ' "$@"\n'
        )
        runtime.chmod(0o700)
        self.runtime = runtime
        self.repo = home / "repo"
        self.repo.mkdir()
        for args in (
            ["init", "-q"],
            [
                "-c",
                "user.email=dev@example.invalid",
                "-c",
                "user.name=Dev",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "start",
            ],
        ):
            subprocess.run(["git", *args], cwd=self.repo, check=True, timeout=30)
        self.env = {
            key: value for key, value in os.environ.items() if key in ("PATH", "LANG")
        }
        self.env.update(
            HOME=str(home),
            PYTHONUNBUFFERED="1",
            PYTHONPATH=str(ROOT),
            BROWSER=shlex.join([sys.executable, str(driver), "%s"]),
            KEEPLANE_FIXTURE_LOGIN=str(self.login_file),
        )
        self.profile = home / ".config/keeplane/account"

    def stops(self, stages):
        """Where the browser waits for the case on its next sign-in."""
        self.login_file.write_text(
            json.dumps(
                {
                    "server": self.stack.server,
                    "username": self.username,
                    "password": self.password,
                    "control": str(self.control),
                    "stops": stages,
                }
            )
        )
        self.login_file.chmod(0o600)
        for path in self.control.glob("*.reached"):
            path.unlink()
        for path in self.control.glob("*.go"):
            path.unlink()

    def start(self, *arguments):
        return subprocess.Popen(
            [sys.executable, str(CLI), *arguments],
            env=self.env,
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def run(self, *arguments, timeout=120):
        process = self.start(*arguments)
        out, err = process.communicate(timeout=timeout)
        return process.returncode, out, err

    def login(self, *extra):
        return self.run(
            "login", "--server", self.stack.server, "--timeout", "60", *extra
        )

    def credential(self):
        path = self.profile / "credential.json"
        return json.loads(path.read_text()) if path.exists() else None

    def reached(self, stage, timeout=60):
        wait_until(lambda: (self.control / (stage + ".reached")).exists(), timeout)

    def go(self, stage):
        (self.control / (stage + ".go")).touch()

    def plan(self, calls, pause_after=None):
        for name in ("calls", "paused", "resume"):
            (self.control / name).unlink(missing_ok=True)
        (self.control / "plan.json").write_text(
            json.dumps({"calls": calls, "pause_after": pause_after})
        )

    def code(self, *, calls=1, pause_after=None, during=None):
        """One `keeplane code` turn; ``during`` runs while it waits between calls."""
        self.plan(calls, pause_after)
        process = self.start("code", "--runtime", str(self.runtime), "Fix the test")
        if during is not None:
            try:
                wait_until(
                    lambda: (
                        (self.control / "paused").exists() or process.poll() is not None
                    ),
                    120,
                )
                assert process.poll() is None, process.communicate()
                during()
            finally:
                (self.control / "resume").touch()
        out, err = process.communicate(timeout=180)
        sent = (
            (self.control / "calls").read_text().splitlines()
            if (self.control / "calls").exists()
            else []
        )
        return process.returncode, out, err, [json.loads(row)["status"] for row in sent]


def wait_until(condition, timeout):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for the case's next step")
        time.sleep(0.1)


def server_status(stack, token):
    """What Keeplane says to a CLI token: 200 or 401."""
    request = Request(
        stack.server + "/api/runtime/session",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    try:
        with DIRECT.open(request, timeout=10) as response:
            return response.status
    except HTTPError as error:
        error.close()
        return error.code


def gateway_status(stack, token, project):
    """What the gateway answers a model call with this token, as the runtime sends it."""
    request = Request(
        stack.gateway + "/chat/completions",
        json.dumps(
            {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}
        ).encode(),
        {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "X-Keeplane-Project-ID": project,
        },
    )
    try:
        with DIRECT.open(request, timeout=30) as response:
            return response.status
    except HTTPError as error:
        error.close()
        return error.code
    except (URLError, OSError):
        return None


def live_tokens(stack, username):
    """The developer's access and refresh tokens in PostgreSQL."""
    return tuple(
        int(
            stack.sql(
                f"SELECT count(*) FROM oauth2_provider_{table} t JOIN accounts_user u "
                f"ON u.id = t.user_id WHERE u.username = '{username}'{live}"
            )
        )
        for table, live in (
            ("accesstoken", ""),
            # A rotated refresh token stays, marked revoked.
            ("refreshtoken", " AND t.revoked IS NULL"),
        )
    )


def recorded_requests(stack, username):
    """How many model requests Keeplane has recorded as the developer's usage."""
    return int(
        stack.sql(
            "SELECT coalesce(sum(t.requests), 0) FROM usage_usagetotal t JOIN "
            f"accounts_user u ON u.id = t.user_id WHERE u.username = '{username}'"
        )
    )


def project_of(developer):
    """The project Keeplane recorded for the developer's repo."""
    code, out, err = developer.run("models")
    assert code == 0, err
    return json.loads(out)["project_id"]


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    reason = unavailable_reason()
    if reason:
        pytest.skip(reason)
    directory = tmp_path_factory.mktemp("sign-in-outage")
    with Stack(directory, APP_IMAGE) as running:
        try:
            status, body = running.admin(
                "POST", f"/api/models/{MODEL}/setup", {"key_choice": "none"}
            )
            assert status == 200, body
            yield running
        except BaseException:
            print(running.logs())
            raise
    report = ROOT / "test-results/e2e"
    if os.environ.get("KEEPLANE_TEST_REPORT_DIR"):
        report = Path(os.environ["KEEPLANE_TEST_REPORT_DIR"])
    report.mkdir(parents=True, exist_ok=True)
    (report / "sign-in-restart-outage.json").write_text(
        json.dumps(REPORT, indent=2) + "\n"
    )


@pytest.fixture
def developer(stack, tmp_path):
    username = "outage-" + uuid.uuid4().hex[:8]
    password = uuid.uuid4().hex + uuid.uuid4().hex
    status, body = stack.admin(
        "POST",
        "/api/users",
        {"username": username, "role": "developer", "password": password},
    )
    assert status == 201, body
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    yield Developer(stack, home, username, password)
    for service in ("database", "app", "gateway"):
        # A failed case must not leave the next one with a service stopped.
        if not stack.compose("ps", "-q", "--status", "running", service, check=False):
            stack.start(service)


def signed_in(developer):
    code, out, err = developer.login()
    assert (code, err) == (0, ""), err
    assert out.endswith("Signed in to Keeplane.\n")
    return developer.credential()


# Browser and device sign-in ----------------------------------------------


@pytest.mark.parametrize("service", ["app", "database"])
def test_sign_in_finishes_after_a_restart_with_the_page_open(stack, developer, service):
    """SRO-01 and SRO-02."""
    developer.stops(["page"])
    process = developer.start("login", "--server", stack.server, "--timeout", "120")
    developer.reached("page")
    stack.restart(service)
    developer.go("page")
    out, err = process.communicate(timeout=120)
    assert (process.returncode, err) == (0, ""), err
    assert out.endswith("Signed in to Keeplane.\n")
    code, who, _ = developer.run("whoami")
    assert code == 0 and json.loads(who)["username"] == developer.username
    assert live_tokens(stack, developer.username) == (1, 1)
    REPORT["SRO-01" if service == "app" else "SRO-02"] = "pass"


@pytest.mark.parametrize("service", ["app", "database"])
def test_sign_in_that_cant_be_exchanged_saves_nothing(stack, developer, service):
    """SRO-03 and SRO-04."""
    developer.stops(["callback"])
    process = developer.start("login", "--server", stack.server, "--timeout", "120")
    developer.reached("callback")
    stack.stop(service)
    try:
        developer.go("callback")
        out, err = process.communicate(timeout=120)
    finally:
        stack.start(service)
    assert (process.returncode, out, err) == (
        1,
        "Opening Keeplane sign-in in your browser.\n",
        UNAVAILABLE,
    )
    # No half-saved sign-in: nothing on this machine, nothing issued.
    assert developer.credential() is None
    assert live_tokens(stack, developer.username) == (0, 0)
    code, _, err = developer.run("whoami")
    assert (code, err) == (1, sign_in_again.SIGNED_OUT_SHORT + "\n")
    # Trying again works.
    developer.stops([])
    signed_in(developer)
    assert live_tokens(stack, developer.username) == (1, 1)
    REPORT["SRO-03" if service == "app" else "SRO-04"] = "pass"


@pytest.mark.parametrize("service", ["app", "database"])
def test_device_sign_in_waits_through_a_restart(stack, developer, service):
    """SRO-05 and SRO-06."""
    process = developer.start(
        "login", "--device", "--server", stack.server, "--timeout", "120"
    )
    announcement = process.stdout.readline().strip()
    prefix = "Open " + stack.server + "/oauth/confirm-device/ and enter code "
    assert announcement.startswith(prefix), announcement
    stack.stop(service)
    # Long enough for the CLI to ask at least once while nothing answers.
    time.sleep(7)
    stack.start(service)
    assert process.poll() is None, process.communicate()
    approved = approve_device(
        stack.server,
        developer.username,
        developer.password,
        announcement[len(prefix) : -1],
    )
    out, err = process.communicate(timeout=60)
    assert approved and (process.returncode, out, err) == (
        0,
        "Signed in to Keeplane.\n",
        "",
    )
    code, who, _ = developer.run("whoami")
    assert code == 0 and json.loads(who)["username"] == developer.username
    assert live_tokens(stack, developer.username) == (1, 1)
    REPORT["SRO-05" if service == "app" else "SRO-06"] = "pass"


# Refresh -----------------------------------------------------------------


@pytest.mark.parametrize("service", ["app", "database"])
def test_refresh_while_down_keeps_the_sign_in_and_a_retry_works(
    stack, developer, service
):
    """SRO-07 and SRO-08."""
    before = signed_in(developer)
    project = project_of(developer)
    stack.stop(service)
    try:
        code, out, err = developer.run("refresh")
    finally:
        stack.start(service)
    assert (code, out, err) == (1, "", REFRESH_UNAVAILABLE)
    assert developer.credential() == before
    assert server_status(stack, before["access_token"]) == 200
    # The retried refresh works, and the old pair is gone everywhere.
    code, out, err = developer.run("refresh")
    assert (code, out, err) == (0, "Keeplane credential refreshed.\n", "")
    after = developer.credential()
    assert after["access_token"] != before["access_token"]
    assert after["refresh_token"] != before["refresh_token"]
    assert after["gateway"] == before["gateway"] == stack.gateway
    assert server_status(stack, before["access_token"]) == 401
    assert gateway_status(stack, before["access_token"], project) == 401
    assert gateway_status(stack, after["access_token"], project) == 200
    assert live_tokens(stack, developer.username) == (1, 1)
    REPORT["SRO-07" if service == "app" else "SRO-08"] = "pass"


def test_a_refresh_answer_lost_in_a_restart_is_never_reused(stack, developer):
    """SRO-09."""
    before = signed_in(developer)
    project = project_of(developer)
    # The server rotates the pair, but the answer never reaches the CLI, as
    # when the app restarts after saving it: the CLI still holds the old pair.
    form = urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": before["client_id"],
            "refresh_token": before["refresh_token"],
        }
    ).encode()
    with DIRECT.open(
        Request(stack.server + "/oauth/token/", form), timeout=10
    ) as answer:
        lost = json.loads(answer.read())
    code, out, err = developer.run("refresh")
    assert (code, out, err) == (1, "", EXPIRED_READ)
    # Reusing the old refresh token withdraws the whole sign-in, the pair the
    # CLI never received included.
    for token in (before["access_token"], lost["access_token"]):
        assert server_status(stack, token) == 401
        assert gateway_status(stack, token, project) == 401
    assert live_tokens(stack, developer.username) == (0, 0)
    calls = stack.provider_calls()
    code, out, err, sent = developer.code()
    assert (code, out, err, sent) == (1, "", EXPIRED_CODE, [])
    assert stack.provider_calls() == calls
    # Signing in again replaces the expired sign-in.
    after = signed_in(developer)
    assert server_status(stack, after["access_token"]) == 200
    REPORT["SRO-09"] = "pass"


def test_refresh_while_the_gateway_is_down(stack, developer):
    """SRO-10."""
    before = signed_in(developer)
    project = project_of(developer)
    stack.stop("gateway")
    try:
        code, out, err = developer.run("refresh")
    finally:
        stack.start("gateway")
    assert (code, out, err) == (0, "Keeplane credential refreshed.\n", "")
    after = developer.credential()
    assert after["gateway"] == before["gateway"] == stack.gateway
    assert gateway_status(stack, before["access_token"], project) == 401
    code, _, err, sent = developer.code()
    assert (code, sent) == (0, [200]) and err.endswith("Answered by coder.\n"), err
    REPORT["SRO-10"] = "pass"


# Coding --------------------------------------------------------------------


@pytest.mark.parametrize("service", ["app", "database", "gateway"])
def test_a_restart_between_two_calls_of_a_task(stack, developer, service):
    """SRO-11, SRO-12 and SRO-13."""
    signed_in(developer)
    calls = stack.provider_calls()
    code, out, err, sent = developer.code(
        calls=2, pause_after=1, during=lambda: stack.restart(service)
    )
    assert (code, sent) == (0, [200, 200]), err
    assert err.endswith("Answered by coder.\n"), err
    assert out.count('"text": "OK"') == 2
    assert stack.provider_calls() == calls + 2
    REPORT[{"app": "SRO-11", "database": "SRO-12", "gateway": "SRO-13"}[service]] = (
        "pass"
    )


@pytest.mark.parametrize(
    ("service", "message", "statuses"),
    [
        ("app", SERVER_DOWN_MORE, {403}),
        # Keeplane's check answers 503 with PostgreSQL down. When that answer
        # comes later than the gateway waits for its check, the gateway
        # refuses the call itself (403, failureMode: deny). Either way no model
        # is tried.
        ("database", SERVER_DOWN_MORE, {403, 503}),
        ("gateway", GATEWAY_DOWN_MORE, {502}),
    ],
    ids=["app", "database", "gateway"],
)
def test_a_task_stops_clearly_when_a_service_goes_down(
    stack, developer, service, message, statuses
):
    """SRO-14, SRO-15 and SRO-16."""
    before = signed_in(developer)
    calls = stack.provider_calls()
    try:
        code, _, err, sent = developer.code(
            calls=2, pause_after=1, during=lambda: stack.stop(service)
        )
    finally:
        stack.start(service)
    assert code == 1 and len(sent) == 2 and sent[0] == 200, err
    assert sent[1] in statuses, (sent, err)
    lines = err.splitlines()
    assert message in lines, err
    # Not mistaken for an expired sign-in, a refused key or a model that is down.
    assert not any(
        text in err
        for text in ("expired", "refused your own key", "is unavailable right now")
    ), err
    assert stack.provider_calls() == calls + 1
    if service == "gateway":
        # Usage doesn't need the gateway: the call it answered is counted.
        assert NOT_RECORDED not in err, err
        assert recorded_requests(stack, developer.username) == 1
    else:
        # Keeplane itself is down, so the CLI says it couldn't record usage.
        assert NOT_RECORDED in err, err
    # The sign-in still works once the service is back.
    assert developer.credential() == before
    code, _, err, sent = developer.code()
    assert (code, sent) == (0, [200]) and err.endswith("Answered by coder.\n"), err
    REPORT[{"app": "SRO-14", "database": "SRO-15", "gateway": "SRO-16"}[service]] = (
        "pass"
    )


def test_a_task_with_the_gateway_or_app_down_from_the_start(stack, developer):
    """SRO-17."""
    signed_in(developer)
    calls = stack.provider_calls()
    stack.stop("gateway")
    try:
        code, _, err, sent = developer.code()
    finally:
        stack.start("gateway")
    # Keeplane's choice of model asks the gateway which models it can use, so
    # Keeplane answers 503 naming the gateway, and the CLI stops before the
    # runtime starts and says the gateway is the cause.
    assert (code, err, sent) == (1, GATEWAY_DOWN_AT_START, [])
    stack.stop("app")
    try:
        code, out, err, sent = developer.code()
    finally:
        stack.start("app")
    # The CLI checks the sign-in first, so the runtime never starts.
    assert (code, out, err, sent) == (1, "", START_UNAVAILABLE, [])
    assert stack.provider_calls() == calls
    REPORT["SRO-17"] = "pass"
