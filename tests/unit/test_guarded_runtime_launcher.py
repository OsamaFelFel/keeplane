"""The launcher's protected-runtime steps, and stopping only its managed gateway.

Cases GRL-01 to GRL-07 in guarded-runtime-launcher-cases.md.
"""

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
    f = SimpleNamespace(
        calls=[], fail=None, same_id=False, wait_calls=0, models=["model-a", "model-b"]
    )

    def run(command, **kwargs):
        args = command[8:]
        f.calls.append(args)
        assert kwargs["cwd"] == tmp_path
        assert kwargs["env"]["KEEPLANE_RUNTIME_PORT"] == "5001"
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
        f.models,
        5001,
        env={},
        wait_ready=ready,
    )
    return f


# GRL-01
def test_fresh_process_and_migration_precede_application_and_enrollment(commands):
    f = commands
    assert f.install() == "http://127.0.0.1:5001/v1"
    assert f.calls[1] == ["stop", "model-enroller", "gateway", "app"]
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
    assert f.calls[-2][-4:] == ["--model", "model-a", "--model", "model-b"]
    assert f.calls[-1][0] == "up" and f.calls[-1][-1] == "model-enroller"


# GRL-02
def test_default_start_registers_clients_and_leaves_enrolment_to_the_enroller(
    commands,
):
    f = commands
    f.models = []
    assert f.install() == "http://127.0.0.1:5001/v1"
    assert [row[-1] for row in f.calls if "register_cli_client" in row] == [
        "register_cli_client",
        "--device",
    ]
    assert not any("install_runtime_guard" in row for row in f.calls)
    assert f.calls[-2][-1] == "app" and f.wait_calls == 1
    assert f.calls[-1][0] == "up" and f.calls[-1][-1] == "model-enroller"
    # No sign-in switch or image is passed: the compose files decide both.
    assert all("KEEPLANE_RUNTIME_OAUTH_ENABLED" not in " ".join(row) for row in f.calls)


# GRL-03
@pytest.mark.parametrize(
    "fault",
    ["same-process", "init", "migration", "registration", "enrollment", "enroller"],
)
def test_every_setup_failure_stops_gateway_and_hides_private_output(commands, fault):
    f = commands
    f.same_id = fault == "same-process"
    f.fail = lambda args: (
        (fault == "init" and "runtime-init" in args)
        or (fault == "migration" and "migrate" in args)
        or (fault == "registration" and "register_cli_client" in args)
        or (fault == "enrollment" and "install_runtime_guard" in args)
        or (fault == "enroller" and args[-1:] == ["model-enroller"] and "up" in args)
    )
    with pytest.raises(RuntimeError, match="gateway is stopped") as error:
        f.install()
    assert "private output" not in str(error.value)
    assert f.calls[-1] == ["stop", "model-enroller", "gateway"]
    assert all("down" not in args and "--volumes" not in args for args in f.calls)


# GRL-04
def test_stop_failure_is_reported_as_unconfirmed(commands):
    f = commands
    f.fail = lambda args: (
        "install_runtime_guard" in args
        or args
        == [
            "stop",
            "model-enroller",
            "gateway",
        ]
    )
    with pytest.raises(RuntimeError, match="could not be confirmed"):
        f.install()


# GRL-05
def test_timeout_still_stops_only_managed_gateway(commands, monkeypatch):
    original = launcher.subprocess.run

    def timeout(command, **kwargs):
        if "install_runtime_guard" in command:
            raise subprocess.TimeoutExpired(command, 120)
        return original(command, **kwargs)

    monkeypatch.setattr(launcher.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="gateway is stopped"):
        commands.install()
    assert commands.calls[-1] == ["stop", "model-enroller", "gateway"]


# GRL-06
@pytest.mark.parametrize(
    ("logs", "expected"),
    [
        (
            ["", "No model is enrolled for protected access.\n"],
            "No model is enrolled for protected access.",
        ),
        (
            ["Starting\nProtected access is ready: 1 model is enrolled.\n"],
            "Protected access is ready: 1 model is enrolled.",
        ),
        ([""] * 5, None),
    ],
)
def test_enroller_report_waits_for_the_first_pass(
    monkeypatch, tmp_path, logs, expected
):
    answers = iter(logs)
    calls, clock = [], [0.0]

    def run(command, **kwargs):
        calls.append(command)
        assert command[-1] == "model-enroller" and "--profile" in command
        return SimpleNamespace(returncode=0, stdout=next(answers, ""))

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(launcher.subprocess, "run", run)
    monkeypatch.setattr(launcher.time, "monotonic", lambda: clock[0])
    assert (
        launcher.enroller_report(tmp_path, tmp_path, env={}, timeout=3, sleep=sleep)
        == expected
    )
    assert len(calls) <= 4
