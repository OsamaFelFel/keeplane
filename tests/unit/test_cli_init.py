"""Unified init is an explicit alias for the existing offline read-only report."""

import json
import sys
from types import SimpleNamespace

import pytest

from components.cli import keeplane, migration_preview
from tests.unit.test_cli_migration_preview import put, state


@pytest.mark.parametrize("mode,status", [("valid", 0), ("blocked", 1), ("invalid", 2)])
def test_unified_preview_preserves_report_boundaries_and_exit_codes(
    tmp_path,
    monkeypatch,
    capsys,
    mode,
    status,
):
    if mode != "invalid":
        (tmp_path / ".git").mkdir()
    put(tmp_path, "CLAUDE.md", "SECRET_INSTRUCTION")
    put(tmp_path, "packages/app/QWEN.md", "SECRET_NESTED")
    put(
        tmp_path,
        ".claude/settings.json",
        '{"hooks":{"command":"SECRET_HOOK"},"future":"SECRET_SETTING"}'
        if mode != "blocked"
        else '{"broken":SECRET_BAD',
    )
    put(tmp_path, ".codex/auth.json", "SECRET_CREDENTIAL")
    before = state(tmp_path)

    def no_account(*_):
        pytest.fail("Preview must not request account or server access")

    monkeypatch.setattr(keeplane, "account", no_account)
    original = migration_preview.read_source

    def guarded(root, relative):
        assert relative.name != "auth.json"
        return original(root, relative)

    monkeypatch.setattr(migration_preview, "read_source", guarded)
    monkeypatch.setattr(
        "sys.argv", ["keeplane", "init", "--preview", "--directory", str(tmp_path)]
    )
    assert keeplane.main() == status
    output = capsys.readouterr()
    assert state(tmp_path) == before and "SECRET_" not in output.out + output.err
    if status != 2:
        result = json.loads(output.out)
        assert result == migration_preview.preview(tmp_path)
        assert result["mode"] == "preview-only" and result["writes"] == []
        assert (
            next(
                entry
                for entry in result["inventory"]
                if entry["source"].endswith("QWEN.md")
            )["proposed_target"]
            == "packages/app/AGENTS.md"
        )


@pytest.mark.parametrize("flags", [[], ["--preview", "--apply"]])
def test_preview_flag_required_and_apply_unavailable(monkeypatch, flags):
    monkeypatch.setattr("sys.argv", ["keeplane", "init", *flags])
    with pytest.raises(SystemExit) as result:
        keeplane.main()
    assert result.value.code == 2


def test_current_directory_and_older_python_are_explicit(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["keeplane", "init", "--preview"])
    assert keeplane.main() == 0
    assert json.loads(capsys.readouterr().out)["inventory"] == []
    monkeypatch.setattr(
        keeplane, "sys", SimpleNamespace(version_info=(3, 9), stderr=sys.stderr)
    )
    assert keeplane.main() == 2
    assert "Python 3.11" in capsys.readouterr().err
