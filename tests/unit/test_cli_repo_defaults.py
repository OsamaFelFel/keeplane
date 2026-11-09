"""`keeplane code "task"` in any repo needs no other flags (Spec 009 ST30, ADR 030).

Cases: tests/unit/cli-repo-defaults-cases.md (REPO-01 to REPO-11).
"""

import json
import os
import stat
import subprocess
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from components.cli import coding, keeplane, opencode_adapter, project_identity
from components.cli.credential_profile import Credential, default_path, opened
from tests.unit import test_cli_project_profile as profile_tests

# The signed-in server double and runtime double shared with the profile tests.
connected = profile_tests.connected
fake_runtime = profile_tests.runtime

REMOTE = "git@example.test:Platform/payments-api.git"
PROJECT = project_identity.remote_project(REMOTE).id


@pytest.fixture
def sample(tmp_path, monkeypatch, connected):
    """A clone with an origin remote, a home folder and the default profile."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    opencode = bin_dir / "opencode"
    opencode.write_text("#!/bin/sh\n")
    opencode.chmod(0o700)
    monkeypatch.setenv("PATH", str(bin_dir))
    repo = tmp_path / "payments-api"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / ".git" / "config").write_text('[remote "origin"]\n\turl = ' + REMOTE + "\n")
    (repo / "src").mkdir()
    monkeypatch.chdir(repo / "src")
    profile = keeplane.profile_path(None, create=True)
    with opened(profile, create=True) as store:
        store.save(
            Credential(
                connected.issuer, connected.actor, connected.access, connected.refresh
            )
        )
    return SimpleNamespace(
        home=home, repo=repo, profile=profile, opencode=opencode, server=connected
    )


@pytest.fixture
def saved_gateway(monkeypatch):
    """The gateway address the server gives at sign-in once task 009-02 lands."""
    real = coding.opened

    @contextmanager
    def with_gateway(path):
        with real(path) as profile:
            credential = profile.load()
            loaded = SimpleNamespace(
                **vars(credential), gateway="https://gateway.test/v1"
            )
            yield SimpleNamespace(load=lambda: loaded)

    monkeypatch.setattr(coding, "opened", with_gateway)


def run(monkeypatch, *arguments):
    monkeypatch.setattr("sys.argv", ["keeplane", *arguments])
    return keeplane.main()


def test_repo_01_default_profile_is_in_the_config_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert default_path() == tmp_path / ".config" / "keeplane" / "account"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert default_path() == tmp_path / "xdg" / "keeplane" / "account"
    assert keeplane.profile_path(None, create=True) == str(default_path())
    assert stat.S_IMODE(os.stat(tmp_path / "xdg" / "keeplane").st_mode) == 0o700
    assert keeplane.profile_path("/given/profile") == "/given/profile"


def test_repo_02_code_with_only_the_task_uses_the_repo_profile_gateway_and_pick(
    sample, fake_runtime, saved_gateway, monkeypatch, capsys
):
    real_run = opencode_adapter.run
    seen = {}

    def adapter(binary, *args, **kwargs):
        seen["binary"] = binary
        return real_run(binary, *args, **kwargs)

    monkeypatch.setattr(opencode_adapter, "run", adapter)
    assert run(monkeypatch, "code", "Make the failing test pass") == 0
    output = capsys.readouterr()
    assert output.out == "Coding finished.\n"
    assert "Using coder for this task, chosen by Keeplane" in output.err
    calls = sample.server.calls
    assert [(row[0], row[1]) for row in calls] == [
        ("GET", "/api/runtime/session"),
        ("POST", "/api/runtime/projects"),
        ("GET", f"/api/runtime/projects/{PROJECT}/models"),
        ("GET", f"/api/runtime/projects/{PROJECT}/task-model"),
    ]
    assert calls[1][3] == {"project_id": PROJECT, "name": "Platform/payments-api"}
    native, options = fake_runtime[1][0]
    config = json.loads(options["env"]["OPENCODE_CONFIG_CONTENT"])
    assert config["providers"]["keeplane"]["headers"] == {
        "X-Keeplane-Project-ID": PROJECT
    }
    assert opencode_adapter.relay_address(
        config["providers"]["keeplane"]["settings"]["baseURL"]
    )
    assert native[native.index("--model") + 1] == "keeplane/coder"
    assert seen["binary"] == str(sample.opencode)
    assert str(options["cwd"]) == str(sample.repo / "src")


def test_repo_03_old_flags_still_override_every_default(
    sample, fake_runtime, monkeypatch, capsys
):
    given = str(uuid.uuid4())
    sample.server.model_ids = ["coder", "general"]
    assert (
        run(
            monkeypatch,
            "code",
            "--profile",
            sample.profile,
            "--project",
            given,
            "--name",
            "Given",
            "--model",
            "general",
            "--runtime",
            str(fake_runtime[0]),
            "--gateway",
            "https://other-gateway.test/v1",
            "Fix it",
        )
        == 0
    )
    calls = sample.server.calls
    assert calls[1][3] == {"project_id": given, "name": "Given"}
    assert not any("task-model" in row[1] for row in calls)
    assert any("model-choice?model_id=general" in row[1] for row in calls)
    assert "chosen by Keeplane" not in capsys.readouterr().err


def test_repo_04_without_a_saved_gateway_the_flag_is_named_and_nothing_is_sent(
    sample, fake_runtime, monkeypatch, capsys
):
    assert run(monkeypatch, "code", "Fix it") == 1
    assert capsys.readouterr().err.strip() == coding.NO_GATEWAY
    assert sample.server.calls == [] and fake_runtime[1] == []
    # Today's flag is enough on its own.
    assert (
        run(monkeypatch, "code", "--gateway", "https://gateway.test/v1", "Fix it") == 0
    )


def test_repo_05_a_bad_saved_gateway_is_refused_before_any_request(
    sample, fake_runtime, monkeypatch, capsys
):
    real = coding.opened

    @contextmanager
    def bad(path):
        with real(path) as profile:
            loaded = SimpleNamespace(
                **vars(profile.load()), gateway="http://remote.test/v1"
            )
            yield SimpleNamespace(load=lambda: loaded)

    monkeypatch.setattr(coding, "opened", bad)
    assert run(monkeypatch, "code", "Fix it") == 1
    assert sample.server.calls == [] and fake_runtime[1] == []


def test_repo_06_runtime_comes_from_the_settings_file_before_path(
    sample, fake_runtime, monkeypatch
):
    from components.cli import settings_file

    settings_file.set_runtime(str(fake_runtime[0]))
    assert coding.find_runtime() == str(fake_runtime[0])
    settings_file.set_runtime(None)
    assert coding.find_runtime() == str(sample.opencode)
    assert coding.find_runtime("~/given") == str(sample.home / "given")


def test_repo_07_no_runtime_found_says_how_to_install_it(sample, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(sample.home))
    assert (
        run(monkeypatch, "code", "--gateway", "https://gateway.test/v1", "Fix it") == 1
    )
    error = capsys.readouterr().err
    assert error.strip() == coding.NO_RUNTIME and "2.0.27" in error
    assert sample.server.calls == []


@pytest.mark.parametrize("reported", ["2.0.26", "opencode 2.0.28", ""])
def test_repo_08_another_runtime_version_is_named_and_not_run(
    sample, fake_runtime, monkeypatch, capsys, reported
):
    monkeypatch.setattr(
        opencode_adapter.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, reported, ""),
    )
    assert (
        run(monkeypatch, "code", "--gateway", "https://gateway.test/v1", "Fix it") == 1
    )
    error = capsys.readouterr().err.strip().splitlines()[-1]
    assert error == coding.WRONG_RUNTIME.format(path=sample.opencode)
    assert fake_runtime[1] == []


def test_repo_08_a_missing_runtime_file_is_named(sample, monkeypatch, capsys):
    sample.opencode.unlink()
    assert (
        run(
            monkeypatch,
            "code",
            "--runtime",
            str(sample.opencode),
            "--gateway",
            "https://gateway.test/v1",
            "Fix it",
        )
        == 1
    )
    assert "is another version or doesn't run" in capsys.readouterr().err


@pytest.mark.parametrize(
    "pick, status", [(None, 200), ("coder", 404), ("outside", 200), ("coder", 503)]
)
def test_repo_09_no_usable_pick_stops_before_the_runtime(
    sample, fake_runtime, monkeypatch, capsys, pick, status
):
    sample.server.task_model, sample.server.task_model_status = pick, status
    assert (
        run(monkeypatch, "code", "--gateway", "https://gateway.test/v1", "Fix it") == 1
    )
    error = capsys.readouterr().err.strip()
    expected = {
        None: coding.NO_ROUTED_MODEL,
        "outside": "This model is not currently allowed for the project.",
    }
    if status == 404:
        assert error == coding.NO_ROUTED_MODEL
    elif status == 503:
        assert error == "Keeplane is temporarily unavailable; retry later."
    else:
        assert error == expected[pick]
    assert fake_runtime[1] == []


def test_repo_10_models_and_register_use_the_repo_in_this_folder(
    sample, monkeypatch, capsys
):
    assert run(monkeypatch, "models") == 0
    assert json.loads(capsys.readouterr().out)["project_id"] == PROJECT
    assert run(monkeypatch, "register-project") == 0
    assert json.loads(capsys.readouterr().out)["project_id"] == PROJECT
    assert sample.server.calls[-1][3] == {
        "project_id": PROJECT,
        "name": "Platform/payments-api",
    }
    given = str(uuid.uuid4())
    assert run(monkeypatch, "models", "--project", given) == 0
    assert json.loads(capsys.readouterr().out)["project_id"] == given
    seen = []
    monkeypatch.setattr(
        keeplane.provider_keys,
        "list_keys",
        lambda profile, project: seen.append(project) or "listed",
    )
    assert run(monkeypatch, "keys", "list") == 0
    assert seen == [PROJECT]


def test_repo_11_outside_a_repo_nothing_is_sent_and_the_flags_are_named(
    sample, fake_runtime, monkeypatch, capsys, tmp_path
):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    monkeypatch.chdir(outside)
    for arguments in (
        ["code", "--gateway", "https://gateway.test/v1", "Fix it"],
        ["models"],
        ["register-project"],
    ):
        assert run(monkeypatch, *arguments) == 1
        assert capsys.readouterr().err.strip() == project_identity.NOT_A_REPO
    assert sample.server.calls == [] and fake_runtime[1] == []
