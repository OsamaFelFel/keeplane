"""A failed or uncertain enrollment must stop only its managed gateway."""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE = Path(__file__).resolve().parents[2] / "deploy/local/guarded_runtime.py"
spec = importlib.util.spec_from_file_location("guarded_runtime", MODULE)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture
def commands(monkeypatch, tmp_path):
    f = SimpleNamespace(calls=[], fail=None, same_id=False, wait_calls=0)

    def run(command, **kwargs):
        args = command[8:]
        f.calls.append(args)
        assert kwargs["cwd"] == tmp_path
        assert kwargs["env"]["KEEPLANE_RUNTIME_PORT"] == "5001"
        assert kwargs["env"]["KEEPLANE_RUNTIME_APP_IMAGE"] == "operator-trial:owned"
        assert kwargs["env"]["KEEPLANE_RUNTIME_OAUTH_ENABLED"] == "1"
        if f.fail and f.fail(args):
            return SimpleNamespace(
                returncode=1, stdout="private output must not be reflected"
            )
        if args == ["ps", "-q", "gateway"]:
            count = sum(row == args for row in f.calls)
            return SimpleNamespace(
                returncode=0, stdout="old" if count == 1 or f.same_id else "fresh"
            )
        return SimpleNamespace(returncode=0, stdout="")

    def ready():
        f.wait_calls += 1

    monkeypatch.setattr(launcher.subprocess, "run", run)
    f.install = lambda: launcher.install(
        tmp_path,
        tmp_path,
        ["model-a", "model-b"],
        5001,
        env={},
        wait_ready=ready,
        app_image="operator-trial:owned",
    )
    return f


def test_fresh_process_and_migration_precede_application_and_enrollment(commands):
    f = commands
    assert f.install() == "http://127.0.0.1:5001/v1"
    assert f.calls[1] == ["stop", "gateway", "app"]
    assert f.calls[2] == ["run", "--rm", "--no-deps", "runtime-init"]
    assert f.calls[3] == [
        "up",
        "-d",
        "--no-build",
        "--pull",
        "never",
        "--no-deps",
        "--force-recreate",
        "gateway",
    ]
    assert f.calls[5][-3:] == ["manage.py", "migrate", "--noinput"]
    assert f.calls[6][-1] == "register_cli_client"
    assert f.calls[7][-2:] == ["register_cli_client", "--device"]
    assert f.calls[8][-1] == "app" and f.wait_calls == 1
    assert f.calls[-1][-4:] == ["--model", "model-a", "--model", "model-b"]


@pytest.mark.parametrize(
    "fault", ["same-process", "init", "migration", "registration", "enrollment"]
)
def test_every_setup_failure_stops_gateway_and_hides_private_output(commands, fault):
    f = commands
    f.same_id = fault == "same-process"
    f.fail = lambda args: (
        (fault == "init" and "runtime-init" in args)
        or (fault == "migration" and "migrate" in args)
        or (fault == "registration" and "register_cli_client" in args)
        or (fault == "enrollment" and "install_runtime_guard" in args)
    )
    with pytest.raises(RuntimeError, match="gateway is stopped") as error:
        f.install()
    assert "private output" not in str(error.value)
    assert f.calls[-1] == ["stop", "gateway"]
    assert all("down" not in args and "--volumes" not in args for args in f.calls)


def test_stop_failure_is_reported_as_unconfirmed(commands):
    f = commands
    f.fail = lambda args: "install_runtime_guard" in args or args == ["stop", "gateway"]
    with pytest.raises(RuntimeError, match="could not be confirmed"):
        f.install()


def test_timeout_still_stops_only_managed_gateway(commands, monkeypatch):
    original = launcher.subprocess.run

    def timeout(command, **kwargs):
        if "install_runtime_guard" in command:
            raise subprocess.TimeoutExpired(command, 120)
        return original(command, **kwargs)

    monkeypatch.setattr(launcher.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="gateway is stopped"):
        commands.install()
    assert commands.calls[-1] == ["stop", "gateway"]
