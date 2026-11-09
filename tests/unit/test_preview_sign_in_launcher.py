"""The default preview starts CLI sign-in and the guarded gateway with no flags.

Cases PSL-01 to PSL-06 in preview-sign-in-launcher-cases.md (Spec 009 ST29 and
ST30, ADR 028). Docker, Node.js and the containers are substituted; the
Compose check renders the files with `docker compose config`, which starts
nothing.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("preview_up", ROOT / "deploy/local/up.py")
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)


@pytest.fixture
def started(monkeypatch, tmp_path):
    """Run up.main() with every outside effect recorded instead of done."""
    f = SimpleNamespace(steps=[], installs=[], fail=None)

    def prepare(port, context_size, runtime_port):
        f.steps.append(("prepare", port, context_size, runtime_port))
        (tmp_path / ".env").write_text(
            f"KEEPLANE_RUNTIME_DIR={tmp_path}\nKEEPLANE_PORT={port}\n"
            f"KEEPLANE_RUNTIME_PORT={runtime_port}\n"
        )

    def install(repo, runtime, models, port, *, env, wait_ready):
        f.installs.append({"models": models, "port": port, "env": env})
        if f.fail:
            raise RuntimeError(f.fail)
        wait_ready()
        return f"http://127.0.0.1:{port}/v1"

    guarded = ModuleType("guarded_runtime")
    guarded.install = install
    guarded.enroller_report = lambda repo, runtime, *, env: (
        "No model is enrolled for protected access."
    )
    monkeypatch.setitem(sys.modules, "guarded_runtime", guarded)
    monkeypatch.setattr(up, "prerequisites", lambda verbose: f.steps.append("check"))
    monkeypatch.setattr(up, "prepare", prepare)
    monkeypatch.setattr(up, "build_admin_ui", lambda verbose: f.steps.append("ui"))
    monkeypatch.setattr(up, "retire_old_preview", lambda: f.steps.append("retire"))
    monkeypatch.setattr(
        up, "run", lambda command, **kwargs: f.steps.append(tuple(command)) or ""
    )
    monkeypatch.setattr(
        up,
        "earlier_database_notices",
        lambda env, since: ["Notice: an earlier preview database was left unused."],
    )
    monkeypatch.setattr(up, "wait_preview", lambda base: f.steps.append(("wait", base)))
    monkeypatch.delenv("KEEPLANE_PORT", raising=False)
    f.main = lambda *argv: up.main(["--runtime-dir", str(tmp_path), *argv])
    return f


# PSL-01
def test_a_plain_start_turns_on_sign_in_and_the_guarded_gateway(started, capsys):
    started.main()
    out = capsys.readouterr().out
    assert started.installs == [
        {"models": [], "port": 5000, "env": started.installs[0]["env"]}
    ]
    assert started.installs[0]["env"]["KEEPLANE_RUNTIME_PORT"] == "5000"
    compose = next(step for step in started.steps if step[:2] == ("docker", "compose"))
    assert "--build" in compose and "--wait" in compose
    # The admin-only check runs first, then again once the new app is up.
    assert [step for step in started.steps if step[0] == "wait"] == [
        ("wait", "http://127.0.0.1:3000")
    ] * 2
    lines = out.splitlines()
    assert "Notice: an earlier preview database was left unused." in lines
    assert "No model is enrolled for protected access." in lines
    assert "Keeplane is ready: http://127.0.0.1:3000" in lines
    assert "Guarded model gateway for the CLI: http://127.0.0.1:5000/v1" in lines
    assert (
        "Sign in from the CLI: keeplane login --server http://127.0.0.1:3000 "
        "--profile PROFILE"
    ) in lines
    assert lines.index("Notice: an earlier preview database was left unused.") < (
        lines.index("Keeplane is ready: http://127.0.0.1:3000")
    )
    assert "First admin username: first-admin" in lines


# PSL-02
@pytest.mark.parametrize(
    "removed",
    [["--runtime-model", "model-a"], ["--runtime-app-image", "trial:local"]],
)
def test_the_old_opt_in_flags_are_gone(started, removed, capsys):
    with pytest.raises(SystemExit) as stopped:
        started.main(*removed)
    assert stopped.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
    assert started.installs == [] and started.steps == []


# PSL-03
def test_the_gateway_port_is_chosen_saved_and_kept_apart(started, capsys):
    started.main("--port", "3080", "--runtime-port", "5001")
    assert ("prepare", 3080, 4096, 5001) in started.steps
    assert started.installs[0]["port"] == 5001
    assert started.installs[0]["env"]["KEEPLANE_RUNTIME_PORT"] == "5001"
    assert "Guarded model gateway for the CLI: http://127.0.0.1:5001/v1" in (
        capsys.readouterr().out
    )
    with pytest.raises(SystemExit):
        started.main("--port", "3080", "--runtime-port", "3080")


# PSL-04
def test_a_failed_runtime_start_is_reported(started, capsys):
    started.fail = "Runtime setup failed; its managed gateway is stopped."
    with pytest.raises(RuntimeError, match="gateway is stopped"):
        started.main()
    assert "Keeplane is ready" not in capsys.readouterr().out


def test_prepare_saves_the_gateway_port(tmp_path, monkeypatch):
    model = tmp_path / "fixture-model.gguf"
    model.write_bytes(b"fixture model")
    monkeypatch.setattr(up, "MODEL", model)
    monkeypatch.setattr(up, "RUNTIME", tmp_path / "local")
    monkeypatch.setattr(
        up, "EXPECTED_MODEL_SHA256", up.hashlib.sha256(b"fixture model").hexdigest()
    )
    up.prepare(port=3000, context_size=4096, runtime_port=5002)
    assert "KEEPLANE_RUNTIME_PORT=5002\n" in (tmp_path / "local/.env").read_text()


def stage_chain(dockerfile, stage):
    """The stage and every stage it starts from, nearest first."""
    bases = {
        name: base
        for base, name in re.findall(r"^FROM (\S+) AS (\S+)$", dockerfile, re.MULTILINE)
    }
    chain = []
    while stage in bases:
        chain.append(stage)
        stage = bases[stage]
    return chain


def body(dockerfile, stage):
    return dockerfile.split(f" AS {stage}\n", 1)[1].split("\nFROM ", 1)[0]


# PSL-05
def test_the_default_image_target_carries_the_hash_pinned_sign_in_packages():
    dockerfile = (ROOT / "components/control-plane/Dockerfile").read_text()
    stages = re.findall(r"^FROM \S+ AS (\S+)$", dockerfile, re.MULTILINE)
    # The last stage is what `docker build` and Compose build by default.
    assert stages[-1] == "preview"
    assert "cli-auth-trial" not in stages
    for target in ("preview", "detection"):
        installs = [
            stage
            for stage in stage_chain(dockerfile, target)
            if "requirements-cli-auth.txt" in body(dockerfile, stage)
        ]
        assert installs == ["sign-in"], target
    section = body(dockerfile, "sign-in")
    assert "--only-binary=:all: --require-hashes --no-deps" in section
    assert "remove_runtime_installers.py" in section
    steps = [line for line in section.splitlines() if line and not line.startswith("#")]
    assert steps[-1] == "USER 65532:65532"
    # Nothing in the preview's chain turns sign-in on; the launcher does.
    for stage in stage_chain(dockerfile, "preview"):
        assert "KEEPLANE_CLI_OAUTH_ENABLED" not in body(dockerfile, stage)


@pytest.fixture(scope="module")
def rendered():
    if not shutil.which("docker"):
        if os.environ.get("CI"):
            pytest.fail("CI must render the preview's Compose files")
        pytest.skip("Docker Compose is not installed here")

    def render(**extra):
        environment = dict(
            os.environ,
            GATEWAY_RUNTIME_KEY_HASH="synthetic",
            GATEWAY_ADMIN_KEY_HASH="synthetic",
            **extra,
        )
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "compose.yaml",
                "-f",
                "deploy/local/runtime.yaml",
                "--profile",
                "*",
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return json.loads(result.stdout)["services"]

    return render


# PSL-06
def test_the_preview_app_and_its_installer_always_accept_cli_sign_in(rendered):
    for extra in ({}, {"KEEPLANE_RUNTIME_OAUTH_ENABLED": "0"}):
        services = rendered(**extra)
        for name in ("app", "runtime-install"):
            assert services[name]["environment"]["KEEPLANE_CLI_OAUTH_ENABLED"] == "1"
        assert services["gateway"]["ports"][0]["host_ip"] == "127.0.0.1"
        assert services["gateway"]["ports"][0]["published"] == "5000"
        assert services["model-enroller"]["command"][-1] == "run_model_enroller"
