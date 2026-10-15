import hashlib
import json

import pytest

from components.cli import migration_preview


def put(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def state(root):
    return {str(path.relative_to(root)): (path.lstat().st_mode, path.readlink().as_posix() if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest())
            for path in root.rglob("*") if path.is_symlink() or path.is_file()}


def test_inventory_preserves_sources_and_never_exports_values(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    put(tmp_path, "CLAUDE.md", "SECRET_INSTRUCTION\n")
    put(tmp_path, "AGENTS.md", "Existing guidance\n")
    put(tmp_path, "packages/app/QWEN.md", "Nested guidance\n")
    put(tmp_path, ".claude/settings.json", json.dumps({"model": "SECRET_MODEL", "hooks": {"command": "SECRET_COMMAND"}, "env": {"KEY": "SECRET_KEY"}, "future": "SECRET_FUTURE"}))
    put(tmp_path, ".codex/config.toml", 'model = "SECRET_CODEX"\nmodel_reasoning_effort = "high"\n[model_providers.private]\napi_key = "SECRET_PROVIDER"\n')
    put(tmp_path, ".qwen/settings.json", '{"model": "SECRET_QWEN", "security": {"token": "SECRET_TOKEN"}}')
    put(tmp_path, ".codex/auth.json", "SECRET_AUTH")
    put(tmp_path, ".qwen/session.json", "SECRET_SESSION")
    before = state(tmp_path)
    original = migration_preview.read_source
    opened = []

    def guarded(root, relative):
        opened.append(relative.as_posix())
        assert relative.name not in {"auth.json", "session.json"}
        return original(root, relative)

    monkeypatch.setattr(migration_preview, "read_source", guarded)
    result = migration_preview.preview(tmp_path)
    assert state(tmp_path) == before
    assert "SECRET_" not in json.dumps(result)
    assert result["writes"] == [] and len(opened) == 6
    assert {finding["kind"] for finding in result["findings"]} >= {"instruction-conflict", "unsupported-settings", "do-not-execute-or-import", "native-setting-review"}
    assert next(entry for entry in result["inventory"] if entry["source"].endswith("QWEN.md"))["proposed_target"] == "packages/app/AGENTS.md"


@pytest.mark.parametrize("content", ["{malformed", "[]", "\"SECRET_SCALAR\""])
def test_malformed_settings_still_return_valid_inventory(tmp_path, content):
    (tmp_path / ".git").mkdir()
    put(tmp_path, "AGENTS.md", "Valid guidance")
    put(tmp_path, ".qwen/settings.json", content)
    result = migration_preview.preview(tmp_path)
    assert len(result["inventory"]) == 2
    assert any(entry["status"] == "blocked" for entry in result["inventory"])
    assert "SECRET" not in json.dumps(result)


def test_symlinks_and_nested_repositories_are_not_read(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    outside = put(tmp_path, "outside/settings.json", '{"model":"SECRET_OUTSIDE"}')
    (root / ".claude").symlink_to(outside.parent, target_is_directory=True)
    (root / "CLAUDE.md").symlink_to(outside)
    put(root, "nested/.git/HEAD", "not read")
    put(root, "nested/QWEN.md", "SECRET_NESTED")
    result = migration_preview.preview(root)
    assert "SECRET" not in json.dumps(result)
    assert result["inventory"] == [{"source": "CLAUDE.md", "status": "blocked"}]
    assert {finding["kind"] for finding in result["findings"]} >= {"skipped-symlink", "skipped-nested-repository"}


def test_sources_are_size_bounded(tmp_path):
    (tmp_path / ".git").mkdir()
    put(tmp_path, "AGENTS.md", "x" * (migration_preview.LIMIT + 1))
    assert migration_preview.preview(tmp_path)["inventory"][0]["status"] == "blocked"


def test_repository_root_is_required(tmp_path):
    with pytest.raises(ValueError, match="repository root"):
        migration_preview.preview(tmp_path)


def test_command_reports_blocked_syntax_without_values(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    put(tmp_path, ".claude/settings.json", '{"model": "SECRET_VALUE",broken')
    monkeypatch.setattr("sys.argv", ["migration_preview", str(tmp_path)])
    assert migration_preview.main() == 1
    output = capsys.readouterr().out
    assert "SECRET_VALUE" not in output and "Malformed JSON." in output
