"""Installed Personal keys, tool turns and history through actual server/gateway."""

import hashlib
import json
import os
import ssl
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from installed_cli_journey import MIGRATION_TEXT, NoRedirects, browser

ROOT = Path("/client")
REPORT = {"passed": False, "stage": "setup", "commands": [], "models": []}


def journey(seed):
    assert os.getuid() == 65532 and not Path("/installed").exists()
    assert set(seed["models"]) == {"openai", "anthropic"}
    assert len(set(seed["models"].values())) == 2
    mounts = {
        line.split()[4]
        for line in Path("/proc/self/mountinfo").read_text().splitlines()
    }
    assert not any(
        path == prefix or path.startswith(prefix + "/")
        for path in mounts
        for prefix in (
            "/installed",
            "/model-tls",
            "/provider-keys",
            "/tls-private",
            "/front-tls",
        )
    )
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in {"PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    }
    home = ROOT / "home"
    home.mkdir(mode=0o700)
    environment.update(
        HOME=str(home),
        PIP_CONFIG_FILE=os.devnull,
        PIP_NO_INDEX="1",
        PYTHONNOUSERSITE="1",
    )
    known = list(seed["synthetic_keys"].values())
    known += [actor["password"] for actor in seed["accounts"].values()]
    outputs = []

    def execute(label, command, *, key=None, denied=False):
        REPORT["stage"] = label
        result = subprocess.run(
            list(map(str, command)),
            cwd=ROOT,
            env=environment,
            input=None if key is None else key + "\n",
            capture_output=True,
            text=True,
            timeout=70,
            check=False,
        )
        REPORT["commands"].append({"name": label, "exit_code": result.returncode})
        outputs.append(result.stdout + result.stderr)
        assert all(secret not in outputs[-1] for secret in known)
        if bool(result.returncode) != denied:
            safe = {"name": label, "stdout": result.stdout, "stderr": result.stderr}
            for field in ("stdout", "stderr"):
                for secret in known:
                    safe[field] = safe[field].replace(secret, "[redacted]")
            path = ROOT / "command-failure.json"
            path.write_text(json.dumps(safe))
            path.chmod(0o600)
        assert bool(result.returncode) == denied
        return result.stdout

    wheel, binary = Path("/package/keeplane.whl"), Path("/runtime/opencode")
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == seed["wheel_sha256"]
    assert (
        hashlib.sha256(binary.read_bytes()).hexdigest()
        == "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"
    )
    package = ROOT / "keeplane_cli-0.0.0-py3-none-any.whl"
    package.write_bytes(wheel.read_bytes())
    execute("venv", [sys.executable, "-m", "venv", ROOT / "venv"])
    python, cli = ROOT / "venv/bin/python", ROOT / "venv/bin/keeplane"
    execute(
        "install", [python, "-m", "pip", "install", "--no-index", "--no-deps", package]
    )
    environment["BROWSER"] = f"{python} {Path(__file__)} --browser %s"
    repository = ROOT / "project"
    repository.mkdir()
    (repository / ".git").mkdir()
    (repository / "CLAUDE.md").write_bytes(MIGRATION_TEXT.encode())
    execute(
        "migration-plan",
        [
            cli,
            "init",
            "--preview",
            "--source",
            "CLAUDE.md",
            "--plan",
            ROOT / "plan.json",
            "--directory",
            repository,
        ],
    )
    applied = json.loads(
        execute(
            "migration-apply",
            [cli, "init", "--apply", ROOT / "plan.json", "--directory", repository],
        )
    )
    assert applied["sha256"] == hashlib.sha256(MIGRATION_TEXT.encode()).hexdigest()
    assert (repository / "AGENTS.md").read_bytes() == (
        repository / "CLAUDE.md"
    ).read_bytes()
    target = repository / "math.py"
    opener = build_opener(ProxyHandler({}), NoRedirects())
    untrusted = build_opener(
        ProxyHandler({}), HTTPSHandler(context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    )
    try:
        with untrusted.open("https://front:8443/health/ready", timeout=5):
            raise AssertionError("Untrusted front certificate was accepted")
    except URLError as error:
        assert isinstance(error.reason, ssl.SSLCertVerificationError)
    REPORT["tls_trust_checked"] = True

    def status():
        with opener.open("https://front:18443/fixture/status", timeout=5) as response:
            current = json.load(response)
        assert not current["failures"]
        return current

    before = status()
    for method, path in (
        ("GET", "/v1/chat/completions"),
        ("POST", "/v1/chat/completions"),
        ("POST", "/fixture/status"),
        ("HEAD", "/fixture/status"),
    ):
        request = Request(
            "https://front:18443" + path,
            data=b"{}" if method == "POST" else None,
            method=method,
        )
        try:
            with opener.open(request, timeout=5):
                raise AssertionError(
                    "Observation endpoint forwarded a non-status request"
                )
        except HTTPError as error:
            assert error.code in {404, 405}
            error.close()
        assert status() == before
    REPORT["status_endpoint_read_only"] = True

    profiles = {}
    for actor in ("a", "b"):
        login = ROOT / "browser-login.json"
        login.write_text(
            json.dumps(dict(seed["accounts"][actor], server=seed["server"]))
        )
        login.chmod(0o600)
        environment["KEEPLANE_FIXTURE_LOGIN"] = str(login)
        profile = ROOT / ("profile-" + actor)
        execute(
            "login-" + actor,
            [cli, "login", "--server", seed["server"], "--profile", profile],
        )
        login.unlink()
        current = json.loads((profile / "credential.json").read_text())
        assert current["actor_id"] == seed["accounts"][actor]["id"]
        known.extend([current["access_token"], current["refresh_token"]])
        profiles[actor] = profile
        assert (
            json.loads(
                execute("identity-" + actor, [cli, "whoami", "--profile", profile])
            )["id"]
            == current["actor_id"]
        )
        execute(
            "project-" + actor,
            [
                cli,
                "register-project",
                "--profile",
                profile,
                "--project",
                seed["project_id"],
                "--name",
                "Personal coding",
            ],
        )

    def key(action, actor, model, label=None):
        command = [cli, "keys", action, "--profile", profiles[actor], "--model", model]
        if label:
            command.append("--key-stdin")
        result = json.loads(
            execute(
                f"key-{action}-{actor}-{model}",
                command,
                key=seed["synthetic_keys"][label] if label else None,
            )
        )
        assert result["model_id"] == model and not result["cleanup_pending"]
        if action != "status":
            assert result["status"] == ("missing" if action == "remove" else "added")
        return result["status"]

    for protocol, model in seed["models"].items():
        assert protocol in {"openai", "anthropic"}
        allowed = json.loads(
            execute(
                "models-" + protocol,
                [
                    cli,
                    "models",
                    "--profile",
                    profiles["a"],
                    "--project",
                    seed["project_id"],
                ],
            )
        )
        assert {"id": model} in allowed["models"]
        histories = {actor: ROOT / (protocol + "-" + actor) for actor in profiles}
        args = [
            "--project",
            seed["project_id"],
            "--name",
            "Personal coding",
            "--model",
            model,
            "--runtime",
            binary,
            "--gateway",
            "https://front:5443/v1",
            "--directory",
            repository,
            "--instructions",
            "AGENTS.md",
            "--timeout",
            "45",
        ]

        def turn(
            actor,
            phase,
            *,
            session=None,
            history_actor=None,
            denied=False,
            histories=histories,
            args=args,
            protocol=protocol,
        ):
            history = histories[history_actor or actor]
            target.write_text("def add(a, b):\n    return a - b\n")
            command = [
                cli,
                "code",
                "--profile",
                profiles[actor],
                *args,
                "--state-dir",
                history,
            ]
            if session:
                command += ["--session", session]
            command += ["PERSONAL_TURN:" + phase + ": fix addition."]
            before = status()
            raw = execute(f"{protocol}-{actor}-{phase}", command, denied=denied)
            if denied:
                assert status() == before
                assert target.read_text().endswith("return a - b\n")
                return None
            identifiers = {
                json.loads(line)["sessionID"]
                for line in raw.splitlines()
                if line.startswith("{") and "sessionID" in json.loads(line)
            }
            assert len(identifiers) == 1
            current = identifiers.pop()
            assert not session or current == session
            assert target.read_text() == "def add(a, b):\n    return a + b\n"
            after = status()
            contacts = after["contacts"][len(before["contacts"]) :]
            assert contacts and all(
                row["provider"] == protocol and not row["validation"]
                for row in contacts
            )
            expected_owner = actor if actor == "b" or phase == "first" else "a_next"
            assert all(row["key_owner"] == expected_owner for row in contacts)
            tools = after["tools"][len(before["tools"]) :]
            assert [row["tool"] for row in tools] == ["read", "edit", None]
            assert all(
                row["protocol"] == protocol
                and row["owner_label"] == expected_owner
                and row["phase"] == phase
                and row["history_checked"] == (phase != "first")
                for row in tools
            )
            return current

        assert key("status", "a", model) == key("status", "b", model) == "missing"
        turn("a", "first", denied=True)
        key("set", "a", model, "a")
        assert key("status", "a", model) == "added"
        first = turn("a", "first")
        assert key("status", "b", model) == "missing"
        key("set", "b", model, "b")
        turn("b", "first", session=first, history_actor="a", denied=True)
        key("set", "a", model, "a_next")
        turn("a", "replace", session=first)
        previous = json.loads((profiles["a"] / "credential.json").read_text())
        execute("refresh-" + protocol, [cli, "refresh", "--profile", profiles["a"]])
        fresh = json.loads((profiles["a"] / "credential.json").read_text())
        assert fresh["actor_id"] == previous["actor_id"]
        assert (
            fresh["access_token"] != previous["access_token"]
            and fresh["refresh_token"] != previous["refresh_token"]
        )
        known.extend([fresh["access_token"], fresh["refresh_token"]])
        turn("a", "resume", session=first)
        key("remove", "a", model)
        assert (
            key("status", "a", model) == "missing"
            and key("status", "b", model) == "added"
        )
        turn("a", "resume", session=first, denied=True)
        other = turn("b", "first")
        turn("a", "first", session=other, history_actor="b", denied=True)
        key("remove", "b", model)
        assert key("status", "b", model) == "missing"
        REPORT["models"].append(
            {
                "protocol": protocol,
                "model_id": model,
                "lifecycle": ["missing", "added", "replaced", "removed"],
                "owner_isolation": True,
                "history_isolation": True,
            }
        )
    for actor, profile in profiles.items():
        credential = json.loads((profile / "credential.json").read_text())
        execute("logout-" + actor, [cli, "logout", "--profile", profile])
        assert not (profile / "credential.json").exists()
        before = status()
        outgoing = Request(
            "https://front:5443/v1/chat/completions",
            data=json.dumps(
                {
                    "model": seed["models"]["openai"],
                    "messages": [{"role": "user", "content": "LOGGED_OUT"}],
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + credential["access_token"],
                "X-Keeplane-Project-ID": seed["project_id"],
            },
        )
        try:
            with opener.open(outgoing, timeout=10):
                raise AssertionError("Logged-out credential dispatched")
        except HTTPError as error:
            assert error.code == 401
            error.close()
        assert status() == before
    for directory in [
        *profiles.values(),
        *(
            ROOT / (protocol + "-" + actor)
            for protocol in seed["models"]
            for actor in profiles
        ),
    ]:
        for file in directory.iterdir():
            assert file.stat().st_mode & 0o777 == 0o600
            assert all(secret.encode() not in file.read_bytes() for secret in known)
    assert all(secret not in "".join(outputs) for secret in known)
    REPORT.update(
        passed=True, stage="complete", provider=status(), retained_secrets=False
    )


if __name__ == "__main__":
    if sys.argv[1:2] == ["--browser"]:
        try:
            browser(sys.argv[2])
        except Exception:  # noqa: BLE001 - never expose callback codes/browser passwords.
            raise SystemExit("Fixture browser could not complete sign-in.") from None
    else:
        try:
            journey(json.loads(sys.stdin.read(16385)))
        except Exception as error:  # noqa: BLE001 - preserve only the safe failed stage.
            REPORT["error_class"] = type(error).__name__
        print(json.dumps(REPORT))
        raise SystemExit(0 if REPORT["passed"] else 1)
