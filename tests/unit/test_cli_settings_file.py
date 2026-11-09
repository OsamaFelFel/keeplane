"""The CLI settings file outside the repo (ADR 030). Cases: cli-settings-file-cases.md."""

import json
import os
import stat
import uuid

import pytest

from components.cli import settings_file
from components.cli.settings_file import SettingsError


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


def write(data):
    target = settings_file.path()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_text(data if isinstance(data, str) else json.dumps(data))
    target.chmod(0o600)
    return target


def test_set_01_the_file_lives_in_the_config_folder(home, monkeypatch):
    assert settings_file.path() == home / ".config" / "keeplane" / "settings.json"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))
    assert settings_file.path() == home / "xdg" / "keeplane" / "settings.json"
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/ignored")
    assert settings_file.path() == home / ".config" / "keeplane" / "settings.json"


def test_set_02_no_file_means_no_settings(home):
    assert settings_file.load() == {}
    assert settings_file.runtime() is None
    assert settings_file.project_model(uuid.uuid4()) is None
    assert settings_file.request_settings("coder") == {}


def test_set_03_saves_are_private_atomic_and_keep_unknown_keys(home):
    write({"future": {"keep": True}, "projects": {}, "models": {"coder": {"x": 1}}})
    project = str(uuid.uuid4())
    settings_file.set_runtime("/opt/opencode/bin/opencode")
    settings_file.set_project_model(project, "coder")
    settings_file.set_request_settings("coder", {"temperature": 0.2})
    target = settings_file.path()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert sorted(p.name for p in target.parent.iterdir()) == [
        ".settings.lock",
        "settings.json",
    ]
    assert json.loads(target.read_text()) == {
        "future": {"keep": True},
        "runtime": "/opt/opencode/bin/opencode",
        "projects": {project: {"model": "coder"}},
        "models": {"coder": {"temperature": 0.2}},
    }
    assert settings_file.runtime() == "/opt/opencode/bin/opencode"
    assert settings_file.project_model(uuid.UUID(project).hex) == "coder"
    assert settings_file.request_settings("coder") == {"temperature": 0.2}
    settings_file.set_project_model(project, None)
    settings_file.set_runtime(None)
    settings_file.set_request_settings("coder", None)
    assert json.loads(target.read_text()) == {
        "future": {"keep": True},
        "projects": {},
        "models": {},
    }


def test_set_04_unknown_keys_at_any_level_are_ignored(home):
    project = str(uuid.uuid4())
    write(
        {
            "runtime": "~/bin/opencode",
            "theme": "dark",
            "projects": {project: {"model": "coder", "later": [1]}},
        }
    )
    assert settings_file.runtime() == str(home / "bin" / "opencode")
    assert settings_file.project_settings(project) == {"model": "coder", "later": [1]}


@pytest.mark.parametrize(
    "data, words",
    [
        ("not json", "isn't valid JSON"),
        ('{"runtime": "a", "runtime": "b"}', "isn't valid JSON"),
        ([], "one JSON object"),
        ({"runtime": "opencode"}, "full path"),
        ({"runtime": 7}, "full path"),
        ({"projects": []}, '"projects" section'),
        ({"projects": {"not-an-id": {}}}, '"projects" entry'),
        ({"projects": {str(uuid.uuid4()): {"model": ""}}}, '"projects" entry'),
        ({"models": {"coder": 0.2}}, '"models" section'),
    ],
)
def test_set_05_known_sections_with_the_wrong_shape_are_refused(home, data, words):
    write(data)
    with pytest.raises(SettingsError) as error:
        settings_file.load()
    assert words in str(error.value) and str(settings_file.path()) in str(error.value)


def test_set_06_a_file_others_can_change_is_refused(home):
    target = write({"runtime": "/tmp/opencode"})
    target.chmod(0o620)
    with pytest.raises(SettingsError, match="only you can change"):
        settings_file.runtime()
    target.chmod(0o600)
    link = target.with_name("other.json")
    target.rename(link)
    os.symlink(link, target)
    with pytest.raises(SettingsError, match="can't be opened"):
        settings_file.runtime()


def test_set_07_bad_values_are_refused_before_saving(home):
    with pytest.raises(SettingsError):
        settings_file.set_project_model("nope", "coder")
    with pytest.raises(SettingsError):
        settings_file.set_project_model(uuid.uuid4(), "bad\nmodel")
    with pytest.raises(SettingsError):
        settings_file.set_request_settings("coder", ["temperature"])
    with pytest.raises(SettingsError, match="full path"):
        settings_file.set_runtime("opencode")
    assert not settings_file.path().exists()
