"""Installed wheel client; browser automation uses real Django account/CSRF routes."""

import hashlib
import json
import os
import ssl
import subprocess
import sys
import uuid
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

RULE = "INSTALLED_CLI_RULE: preserve the addition function's interface."
MIGRATION_TEXT = RULE + "\nPRIVATE_MIGRATION_INSTRUCTION\n"
ROOT = Path("/client")
REPORT = {"passed": False, "stage": "setup", "commands": []}


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class HiddenFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attributes):
        values = dict(attributes)
        if tag == "input" and values.get("type") == "hidden" and "name" in values:
            self.values[values["name"]] = values.get("value", "")


def browser(url):
    login = json.loads(Path(os.environ["KEEPLANE_FIXTURE_LOGIN"]).read_text())
    server = login["server"]
    assert url.startswith(server + "/oauth/authorize/?")
    opener = build_opener(
        ProxyHandler({}), HTTPCookieProcessor(CookieJar()), NoRedirects()
    )

    def request(target, data=None, *, expected=200, csrf=None):
        headers = {"Origin": server}
        if csrf:
            headers.update({"Content-Type": "application/json", "X-CSRFToken": csrf})
            payload = json.dumps(data).encode()
        else:
            payload = None if data is None else urlencode(data).encode()
        outgoing = Request(target, data=payload, headers=headers)
        try:
            with opener.open(outgoing, timeout=8) as response:
                assert response.status == expected
                return response.read(65536), response.headers
        except HTTPError as error:
            try:
                assert error.code == expected
                return error.read(65536), error.headers
            finally:
                error.close()

    _, headers = request(url, expected=302)
    returned = parse_qs(urlsplit(headers["Location"]).query)["return_to"][0]
    assert headers["Location"].startswith("/sign-in?") and returned.startswith(
        "/oauth/authorize/?"
    )
    raw, _ = request(server + "/api/auth-options")
    request(
        server + "/api/session",
        {"username": login["username"], "password": login["password"]},
        csrf=json.loads(raw)["csrf_token"],
    )
    page, _ = request(server + returned)
    assert b"Allow CLI access?" in page
    fields = HiddenFields()
    fields.feed(page.decode())
    fields.values["allow"] = "true"
    _, headers = request(server + "/oauth/authorize/", fields.values, expected=302)
    callback = urlsplit(headers["Location"])
    assert callback.hostname == "127.0.0.1" and callback.path == "/callback"
    values = parse_qs(callback.query)
    assert values["iss"] == [server]
    assert values["state"] == parse_qs(urlsplit(url).query)["state"]
    request(headers["Location"])


def journey(seed):
    REPORT["stage"] = "client-filesystem-isolation"
    assert os.getuid() == 65532
    assert not Path("/installed").exists()
    mounts = {
        line.split()[4]
        for line in Path("/proc/self/mountinfo").read_text().splitlines()
    }
    assert not any(
        path == "/installed" or path.startswith("/installed/") for path in mounts
    )
    REPORT["stage"] = "artifact-pins"
    binary = Path("/runtime/opencode")
    assert (
        hashlib.sha256(binary.read_bytes()).hexdigest()
        == "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"
    )
    wheel = Path("/package/keeplane.whl")
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == seed["wheel_sha256"]
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in {"PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    }
    environment.update(
        PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX="1", PYTHONNOUSERSITE="1"
    )
    home = ROOT / "home"
    home.mkdir(mode=0o700)
    environment["HOME"] = str(home)
    known = []
    output = []

    def execute(label, command, *, expected=0):
        REPORT["stage"] = label
        process = subprocess.run(
            list(map(str, command)),
            env=environment,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=70,
            check=False,
        )
        REPORT["commands"].append({"name": label, "exit_code": process.returncode})
        output.append(process.stdout + process.stderr)
        if process.returncode != expected:
            failed = ROOT / "command-failure.json"
            failed.write_text(
                json.dumps(
                    {
                        "command": label,
                        "stdout": process.stdout,
                        "stderr": process.stderr,
                    }
                )
            )
            failed.chmod(0o600)
        assert all(secret not in process.stdout + process.stderr for secret in known)
        assert process.returncode == expected, "Installed CLI command failed"
        return process.stdout

    execute("create-venv", [sys.executable, "-m", "venv", ROOT / "venv"])
    python, cli = ROOT / "venv/bin/python", ROOT / "venv/bin/keeplane"
    # pip checks the filename: retain the canonical wheel name while mounting it.
    package = ROOT / "keeplane_cli-0.0.0-py3-none-any.whl"
    package.write_bytes(wheel.read_bytes())
    execute(
        "offline-install",
        [python, "-m", "pip", "install", "--no-index", "--no-deps", package],
    )
    assert "init" in execute("help", [cli, "--help"])
    environment["BROWSER"] = f"{python} {Path(__file__)} --browser %s"
    repository, history = ROOT / "project", ROOT / "history"
    repository.mkdir()
    (repository / ".git").mkdir()
    (repository / "CLAUDE.md").write_bytes(MIGRATION_TEXT.encode())
    target = repository / "math.py"
    target.write_text("def add(a, b):\n    return a - b\n")
    before = {
        path.name: path.read_bytes() for path in repository.iterdir() if path.is_file()
    }
    original_modes = {
        path.name: path.stat().st_mode
        for path in repository.iterdir()
        if path.is_file()
    }
    preview = execute(
        "init-preview", [cli, "init", "--preview", "--directory", repository]
    )
    parsed = json.loads(preview)
    assert parsed["writes"] == [] and parsed["mode"] == "preview-only"
    assert "PRIVATE_MIGRATION_INSTRUCTION" not in preview
    assert before == {
        path.name: path.read_bytes() for path in repository.iterdir() if path.is_file()
    }
    plan = ROOT / "migration.json"
    reviewed = execute(
        "init-save-plan",
        [
            cli,
            "init",
            "--preview",
            "--source",
            "CLAUDE.md",
            "--plan",
            plan,
            "--directory",
            repository,
        ],
    )
    parsed = json.loads(reviewed)
    assert parsed["writes"] == [] and parsed["mode"] == "preview-only"
    assert parsed["plan"]["source"] == "CLAUDE.md"
    assert parsed["plan"]["target"] == "AGENTS.md"
    assert "PRIVATE_MIGRATION_INSTRUCTION" not in reviewed + plan.read_text()
    assert before == {
        path.name: path.read_bytes() for path in repository.iterdir() if path.is_file()
    }
    applied = json.loads(
        execute(
            "init-apply-plan", [cli, "init", "--apply", plan, "--directory", repository]
        )
    )
    digest = hashlib.sha256(before["CLAUDE.md"]).hexdigest()
    assert applied == {
        "mode": "partial-instruction-migration",
        "source": "CLAUDE.md",
        "created": "AGENTS.md",
        "sha256": digest,
        "originals": "kept",
    }
    assert (repository / "AGENTS.md").read_bytes() == before["CLAUDE.md"]
    assert (repository / "AGENTS.md").stat().st_mode & 0o777 == 0o600
    assert plan.stat().st_mode & 0o777 == 0o600
    assert all((repository / name).read_bytes() == raw for name, raw in before.items())
    assert all(
        (repository / name).stat().st_mode == mode
        for name, mode in original_modes.items()
    )
    assert {path.name for path in repository.iterdir()} == {
        ".git",
        "CLAUDE.md",
        "AGENTS.md",
        "math.py",
    }
    REPORT["migration"] = {
        "source": "CLAUDE.md",
        "created": "AGENTS.md",
        "sha256": digest,
        "original_bytes_and_modes_preserved": True,
        "plan_contains_content": False,
    }

    def login(label):
        actor = seed["accounts"][label]
        login_file = ROOT / "browser-login.json"
        login_file.write_text(json.dumps(dict(actor, server=seed["server"])))
        login_file.chmod(0o600)
        environment["KEEPLANE_FIXTURE_LOGIN"] = str(login_file)
        profile = ROOT / ("profile-" + label)
        execute(
            "login-" + label,
            [
                cli,
                "login",
                "--profile",
                profile,
                "--server",
                seed["server"],
                "--timeout",
                "20",
            ],
        )
        credential = json.loads((profile / "credential.json").read_text())
        assert credential["actor_id"] == actor["id"]
        known.extend([credential["access_token"], credential["refresh_token"]])
        return profile, credential

    opener = build_opener(ProxyHandler({}), NoRedirects())

    # A wrong trust store must fail; no verification bypass is enabled for either
    # the installed Python client or the native runtime subprocess.
    untrusted = build_opener(
        ProxyHandler({}), HTTPSHandler(context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    )
    try:
        with untrusted.open("https://front:18443/fixture/status", timeout=5):
            raise AssertionError("Untrusted TLS certificate was accepted")
    except URLError as error:
        assert isinstance(error.reason, ssl.SSLCertVerificationError)
    REPORT["tls_trust_checked"] = True

    def status():
        with opener.open("https://front:18443/fixture/status", timeout=5) as response:
            data = json.load(response)
        assert not data["failures"]
        return data

    profile, initial = login("a")
    assert (
        json.loads(execute("whoami", [cli, "whoami", "--profile", profile]))["id"]
        == initial["actor_id"]
    )
    project = str(uuid.UUID(seed["project_id"]))

    # The developer has a separate network namespace. The private loopback admin
    # listener cannot be reached through service DNS, and raw dispatch needs the
    # operator credential, which is confined to the server volume.
    REPORT["stage"] = "private-listener-isolation"
    contacts = status()["contacts"]
    for path in ("/config_dump", "/debug/trace"):
        try:
            with opener.open("http://gateway:15000" + path, timeout=2):
                raise AssertionError("Developer reached the private admin listener")
        except URLError as error:
            assert not isinstance(error, HTTPError)
    for path, payload in (
        ("/api/config", None),
        (
            "/v1/chat/completions",
            json.dumps(
                {
                    "model": seed["model"],
                    "messages": [{"role": "user", "content": "RAW_DENIED"}],
                }
            ).encode(),
        ),
    ):
        try:
            with opener.open(
                Request("http://gateway:4000" + path, data=payload), timeout=5
            ):
                raise AssertionError("Developer reached private operator state")
        except HTTPError as error:
            assert error.code in {401, 403}
            error.close()
    assert status()["contacts"] == contacts

    def denied_access(token):
        request = Request(
            "https://front:5443/v1/chat/completions",
            data=json.dumps(
                {
                    "model": seed["model"],
                    "messages": [{"role": "user", "content": "MUST_NOT_DISPATCH"}],
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
                "X-Keeplane-Project-ID": project,
            },
        )
        try:
            with opener.open(request, timeout=10):
                raise AssertionError("Withdrawn credential reached protected access")
        except HTTPError as error:
            assert error.code == 401
            error.close()

    args = [
        "--project",
        project,
        "--name",
        "Installed CLI project",
        "--model",
        seed["model"],
        "--runtime",
        binary,
        "--gateway",
        "https://front:5443/v1",
        "--directory",
        repository,
        "--state-dir",
        history,
        "--instructions",
        "AGENTS.md",
        "--timeout",
        "45",
    ]
    first = execute(
        "first-turn",
        [
            cli,
            "code",
            "--profile",
            profile,
            *args,
            "FIRST_SAVED_TURN: fix addition in math.py.",
        ],
    )
    session_ids = {
        json.loads(line)["sessionID"]
        for line in first.splitlines()
        if line.startswith("{") and "sessionID" in json.loads(line)
    }
    assert len(session_ids) == 1
    session = session_ids.pop()
    assert target.read_text() == "def add(a, b):\n    return a + b\n"
    assert status()["tools"] == ["read", "edit"]
    catalog = json.loads(
        execute("models", [cli, "models", "--profile", profile, "--project", project])
    )
    assert {"id": seed["model"]} in catalog["models"]
    execute("refresh", [cli, "refresh", "--profile", profile])
    fresh = json.loads((profile / "credential.json").read_text())
    assert fresh["actor_id"] == initial["actor_id"]
    assert (
        fresh["access_token"] != initial["access_token"]
        and fresh["refresh_token"] != initial["refresh_token"]
    )
    known.extend([fresh["access_token"], fresh["refresh_token"]])
    contacts = status()["contacts"]
    REPORT["stage"] = "rotated-access-denied"
    denied_access(initial["access_token"])
    assert status()["contacts"] == contacts
    target.write_text("def add(a, b):\n    return a - b\n")
    second = execute(
        "resumed-turn",
        [
            cli,
            "code",
            "--profile",
            profile,
            *args,
            "--session",
            session,
            "SECOND_RESUMED_TURN: fix addition again.",
        ],
    )
    assert any(
        json.loads(line).get("sessionID") == session
        for line in second.splitlines()
        if line.startswith("{")
    )
    assert target.read_text() == "def add(a, b):\n    return a + b\n"
    current = status()
    assert (
        current["tools"] == ["read", "edit", "read", "edit"]
        and current["continued"] >= 3
    )
    if seed.get("cancellation"):
        from installed_cli_cancel import check

        REPORT["stage"] = "cancellation"
        fresh, REPORT["cancellation"] = check(
            cli,
            profile,
            args,
            session,
            repository,
            environment,
            execute,
            status,
            known,
            output,
        )
        current = status()
    contacts = current["contacts"]
    wrong = list(args)
    wrong[1] = str(uuid.UUID(seed["alternate_project_id"]))
    allowed = json.loads(
        execute(
            "other-project-models",
            [cli, "models", "--profile", profile, "--project", wrong[1]],
        )
    )
    assert {"id": seed["model"]} in allowed["models"]
    execute(
        "project-bound-history",
        [
            cli,
            "code",
            "--profile",
            profile,
            *wrong,
            "--session",
            session,
            "CROSS_PROJECT: must not dispatch.",
        ],
        expected=1,
    )
    other, _ = login("b")
    execute(
        "other-account-project",
        [
            cli,
            "register-project",
            "--profile",
            other,
            "--project",
            project,
            "--name",
            "Installed CLI project",
        ],
    )
    allowed = json.loads(
        execute(
            "other-account-models",
            [cli, "models", "--profile", other, "--project", project],
        )
    )
    assert {"id": seed["model"]} in allowed["models"]
    execute(
        "account-bound-history",
        [
            cli,
            "code",
            "--profile",
            other,
            *args,
            "--session",
            session,
            "CROSS_ACCOUNT: must not dispatch.",
        ],
        expected=1,
    )
    assert status()["contacts"] == contacts
    execute("logout-b", [cli, "logout", "--profile", other])
    execute("logout-a", [cli, "logout", "--profile", profile])
    REPORT["stage"] = "logout-denied"
    denied_access(fresh["access_token"])
    request = Request(
        seed["server"] + "/oauth/token/",
        data=urlencode(
            {
                "grant_type": "refresh_token",
                "client_id": "keeplane-cli",
                "refresh_token": fresh["refresh_token"],
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with opener.open(request, timeout=10):
            raise AssertionError("Revoked refresh credential was accepted")
    except HTTPError as error:
        assert error.code == 400
        error.close()
    assert status()["contacts"] == contacts
    for path in history.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
        assert all(secret.encode() not in path.read_bytes() for secret in known)
    assert (
        not (profile / "credential.json").exists()
        and not (other / "credential.json").exists()
    )
    assert all(secret not in "".join(output) for secret in known)
    REPORT.update(
        passed=True,
        stage="complete",
        actor_id=initial["actor_id"],
        project_id=project,
        session_id=session,
        provider=status(),
        retained_credentials=False,
    )


if __name__ == "__main__":
    if sys.argv[1:2] == ["--browser"]:
        try:
            browser(sys.argv[2])
        except Exception:  # noqa: BLE001 - keep callback codes and browser passwords out of diagnostics.
            print("Fixture browser could not complete sign-in.", file=sys.stderr)
            raise SystemExit(1) from None
    else:
        try:
            journey(json.loads(sys.stdin.read(8193)))
        except Exception as error:  # noqa: BLE001 - retain a safe failed-stage report for the container driver.
            REPORT["error_class"] = type(error).__name__
        (ROOT / "result.json").write_text(json.dumps(REPORT))
        print(json.dumps(REPORT))
        raise SystemExit(0 if REPORT["passed"] else 1)
