import hashlib
import json
import os
import subprocess

import pytest

from components.cli import opencode_adapter
from components.cli.instructions import snapshot


def test_adapter_uses_immutable_reviewed_text_without_importing_project_settings(
    tmp_path, monkeypatch
):
    binary, source = tmp_path / "runtime", tmp_path / "AGENTS.md"
    binary.touch()
    source.write_text("Reviewed UTF-8 rule: العربية\n")
    raw = source.read_bytes()
    (tmp_path / "opencode.json").write_text(
        '{"plugins":["hostile"],"providers":{"keeplane":{"settings":{"apiKey":"repo-key"}}}}'
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "2.0.27", ""),
    )

    def coding(command, **options):
        source.write_text("Edited after the snapshot")
        config = json.loads(options["env"]["OPENCODE_CONFIG_CONTENT"])
        assert options["env"]["OPENCODE_CONFIG_PROJECT_DISABLE"] == "1"
        assert config["providers"]["keeplane"]["settings"] == {
            "baseURL": "https://gateway.test/v1"
        }
        assert "repo-key" not in json.dumps(config) and len(config["plugins"]) == 1
        manifest = config["plugins"][0]["options"]
        assert manifest == {
            "directory": str(tmp_path),
            "sources": [
                {
                    "path": "AGENTS.md",
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "content": raw.decode(),
                }
            ],
        }
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(opencode_adapter, "coding_turn", coding)
    assert (
        opencode_adapter.run(
            binary,
            tmp_path,
            "https://gateway.test/v1",
            "coder",
            "Fix.",
            "grant",
            instructions=[source],
        ).returncode
        == 0
    )


@pytest.mark.parametrize(
    "kind",
    ["outside", "nested", "duplicate", "symlink", "parent-link", "fifo", "directory"],
)
def test_refuses_unsafe_or_differently_scoped_sources(tmp_path, kind):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "AGENTS.md"
    source.write_text("Reviewed rule")
    sources = [source]
    if kind == "outside":
        source = tmp_path / "outside"
        source.write_text("Outside rule")
        sources = [source]
    elif kind == "nested":
        (root / "nested").mkdir()
        source = root / "nested/AGENTS.md"
        source.write_text("Nested rule")
        sources = [source]
    elif kind == "duplicate":
        sources *= 2
    elif kind == "parent-link":
        (root / "link").symlink_to(root, target_is_directory=True)
        sources = [root / "link/AGENTS.md"]
    else:
        source.unlink()
        if kind == "symlink":
            source.symlink_to(tmp_path / "outside")
        elif kind == "fifo":
            os.mkfifo(source)
        else:
            source.mkdir()
    with pytest.raises(ValueError):
        snapshot(root, sources)


@pytest.mark.parametrize(
    "raw", [b"", b" \n", b"bad\0rule", b"bad\xffrule", b"x" * 32769]
)
def test_refuses_invalid_or_oversized_text(tmp_path, raw):
    (tmp_path / "AGENTS.md").write_bytes(raw)
    with pytest.raises(ValueError):
        snapshot(tmp_path, ["AGENTS.md"])


def test_total_and_source_count_bounds(tmp_path):
    for index in range(9):
        (tmp_path / str(index)).write_bytes(b"x" * 32768)
    assert len(snapshot(tmp_path, ["0", "1"])["sources"]) == 2
    for sources in (["0", "1", "2"], [str(index) for index in range(9)]):
        with pytest.raises(ValueError):
            snapshot(tmp_path, sources)


def test_expanded_configuration_is_bounded_before_any_runtime_launch(
    tmp_path, monkeypatch
):
    binary = tmp_path / "runtime"
    binary.touch()
    sources = [tmp_path / name for name in ("AGENTS.md", "rules.md")]
    for source in sources:
        source.write_bytes(b'"' * 32768)
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: pytest.fail("Runtime launched")
    )
    monkeypatch.setattr(
        opencode_adapter,
        "coding_turn",
        lambda *args, **kwargs: pytest.fail("Runtime launched"),
    )
    with pytest.raises(ValueError, match="Serialized runtime configuration exceeds"):
        opencode_adapter.run(
            binary,
            tmp_path,
            "https://gateway.test/v1",
            "coder",
            "Fix.",
            "grant",
            instructions=sources,
        )
