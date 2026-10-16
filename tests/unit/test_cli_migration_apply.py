"""Real filesystem controls for one explicit instruction copy, never conversion."""

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from components.cli import instructions, keeplane
from components.cli import migration_apply as migration
from tests.unit.test_cli_migration_preview import state


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git/HEAD").write_text("ref: refs/heads/fixture\n")
    (root / "CLAUDE.md").write_bytes("PRIVATE_RULE\r\nKeep café.\r\n".encode())
    plan = tmp_path / "migration.json"
    return root, plan


def planned(project):
    root, plan = project
    migration.review(root, "CLAUDE.md", plan)
    return root, plan


def test_cli_review_then_confirmed_copy_preserves_originals(project, monkeypatch, capsys):
    root, plan = project
    (root / ".claude").mkdir()
    (root / ".claude/settings.json").write_text('{"hooks":{"command":"PRIVATE_HOOK"}}')
    before = state(root)
    monkeypatch.setattr(keeplane, "account", lambda *_: pytest.fail("No account/network in migration"))
    monkeypatch.setattr("sys.argv", ["keeplane", "init", "--preview", "--directory", str(root),
                                    "--source", "CLAUDE.md", "--plan", str(plan)])
    assert keeplane.main() == 0
    assert state(root) == before and "PRIVATE_" not in capsys.readouterr().out
    assert "PRIVATE_" not in plan.read_text() and stat.S_IMODE(plan.stat().st_mode) == 0o600
    monkeypatch.setattr("sys.argv", ["keeplane", "init", "--apply", str(plan), "--directory", str(root)])
    assert keeplane.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "partial-instruction-migration" and result["originals"] == "kept"
    assert (root / "AGENTS.md").read_bytes() == (root / "CLAUDE.md").read_bytes()
    assert stat.S_IMODE((root / "AGENTS.md").stat().st_mode) == 0o600
    assert {name: value for name, value in state(root).items() if name != "AGENTS.md"} == before
    assert instructions.snapshot(root, ["AGENTS.md"])["sources"][0]["sha256"] == result["sha256"]
    with pytest.raises(migration.MigrationError, match="already exists"):
        migration.apply(root, plan)


@pytest.mark.parametrize("change", ["changed", "added", "conflict", "target", "symlink", "hardlink", "fifo"])
def test_changed_or_unsafe_sources_and_target_are_refused(project, change):
    root, plan = planned(project)
    source = root / "CLAUDE.md"
    if change == "changed":
        source.write_text("Changed after preview")
    elif change in {"added", "conflict"}:
        (root / "QWEN.md").write_bytes(source.read_bytes() if change == "added" else b"Conflicting guidance")
    elif change == "target":
        (root / "AGENTS.md").write_text("Keep this existing file")
    else:
        source.rename(root / "original")
        if change == "symlink":
            source.symlink_to(root / "original")
        elif change == "hardlink":
            os.link(root / "original", source)
        else:
            os.mkfifo(source)
    with pytest.raises((migration.MigrationError, OSError)):
        migration.apply(root, plan)
    assert not list(root.glob(".keeplane-init-*.pending"))
    if change != "target":
        assert not (root / "AGENTS.md").exists()


@pytest.mark.parametrize("field,value", [("target", "../AGENTS.md"), ("source", ".codex/auth.json"),
                                        ("directory", "/different/repo"), ("unknown", "PRIVATE_VALUE")])
def test_untrusted_plan_cannot_choose_other_writes(project, field, value):
    root, plan = planned(project)
    data = json.loads(plan.read_text())
    data[field] = value
    plan.write_text(json.dumps(data))
    with pytest.raises(migration.MigrationError, match="invalid|different"):
        migration.apply(root, plan)
    assert not (root / "AGENTS.md").exists()


@pytest.mark.parametrize("timing", ["before-link", "after-link", "directory-sync"])
def test_failures_before_publish_clean_up_and_after_publish_require_review(project, monkeypatch, timing):
    root, plan = planned(project)
    reviewed_bytes = (root / "CLAUDE.md").read_bytes()
    original_link, original_sync = os.link, os.fsync
    failed = False

    def link(*args, **kwargs):
        if timing == "before-link":
            raise OSError("synthetic create failure")
        original_link(*args, **kwargs)
        if timing == "after-link":
            (root / "CLAUDE.md").write_text("New source revision")

    def sync(descriptor):
        nonlocal failed
        if timing == "directory-sync" and stat.S_ISDIR(os.fstat(descriptor).st_mode) and not failed:
            failed = True
            raise OSError("synthetic directory durability failure")
        return original_sync(descriptor)

    with monkeypatch.context() as context:
        context.setattr(os, "link", link)
        context.setattr(os, "fsync", sync)
        with pytest.raises((migration.MigrationError, OSError)):
            migration.apply(root, plan)
    assert not list(root.glob(".keeplane-init-*.pending"))
    assert (root / "CLAUDE.md").read_text().startswith("New source" if timing == "after-link" else "PRIVATE_RULE")
    if timing == "before-link":
        assert not (root / "AGENTS.md").exists()
        migration.apply(root, plan)
    else:
        assert (root / "AGENTS.md").read_bytes() == reviewed_bytes
        with pytest.raises(migration.MigrationError, match="already exists"):
            migration.apply(root, plan)


@pytest.mark.parametrize("replace", [False, True])
def test_failed_sync_does_not_erase_a_new_user_edit(project, monkeypatch, replace):
    root, plan = planned(project)
    original = os.fsync

    def sync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            if replace:
                (root / "AGENTS.md").unlink()
            (root / "AGENTS.md").write_text("User edit after publication")
            raise OSError("synthetic sync failure")
        return original(descriptor)

    monkeypatch.setattr(os, "fsync", sync)
    with pytest.raises(migration.MigrationError, match="outcome needs review"):
        migration.apply(root, plan)
    assert (root / "AGENTS.md").read_text() == "User edit after publication"
    assert (root / "CLAUDE.md").read_text().startswith("PRIVATE_RULE")


def test_two_confirmations_cannot_overwrite_each_other(project, monkeypatch):
    root, plan = planned(project)
    barrier, original = Barrier(2), os.link

    def link(*args, **kwargs):
        barrier.wait(timeout=3)
        return original(*args, **kwargs)

    def attempt():
        try:
            return migration.apply(root, plan)["created"]
        except (migration.MigrationError, OSError):
            return "refused"

    monkeypatch.setattr(os, "link", link)
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(lambda _: attempt(), range(2))) == ["AGENTS.md", "refused"]
    assert (root / "AGENTS.md").read_bytes() == (root / "CLAUDE.md").read_bytes()
    assert not list(root.glob(".keeplane-init-*.pending"))


def test_qwen_copy_and_conflicting_plan_refusal(project):
    root, plan = project
    (root / "CLAUDE.md").rename(root / "QWEN.md")
    migration.review(root, "QWEN.md", plan)
    migration.apply(root, plan)
    assert (root / "AGENTS.md").read_bytes() == (root / "QWEN.md").read_bytes()
    with pytest.raises(migration.MigrationError, match="already exists"):
        migration.review(root, "QWEN.md", plan.with_name("second.json"))


@pytest.mark.parametrize("content", [b"", b"\0", b"\xff", b"x" * (instructions.LIMIT + 1)])
def test_plan_accepts_only_runtime_supported_text(project, content):
    root, plan = project
    (root / "CLAUDE.md").write_bytes(content)
    with pytest.raises((migration.MigrationError, UnicodeError)):
        migration.review(root, "CLAUDE.md", plan)
    assert not plan.exists() and not (root / "AGENTS.md").exists()


@pytest.mark.parametrize("change", ["symlink", "hardlink", "permissions", "duplicate", "malformed", "oversized"])
def test_saved_plan_is_private_regular_bounded_and_strict(project, change):
    root, plan = planned(project)
    if change in {"symlink", "hardlink"}:
        original = plan.with_name("original.json")
        plan.rename(original)
        if change == "symlink":
            plan.symlink_to(original)
        else:
            os.link(original, plan)
    elif change == "permissions":
        plan.chmod(0o644)
    elif change == "oversized":
        plan.write_text("x" * 4097)
    else:
        plan.write_text('{"version":1,"version":1}' if change == "duplicate" else "not json")
    with pytest.raises((migration.MigrationError, OSError, ValueError)):
        migration.apply(root, plan)
    assert not (root / "AGENTS.md").exists()


def test_target_created_during_publication_is_preserved(project, monkeypatch):
    root, plan = planned(project)
    original = os.link

    def link(*args, **kwargs):
        (root / "AGENTS.md").write_text("Concurrent user file")
        return original(*args, **kwargs)

    monkeypatch.setattr(os, "link", link)
    with pytest.raises(FileExistsError):
        migration.apply(root, plan)
    assert (root / "AGENTS.md").read_text() == "Concurrent user file"
    assert not list(root.glob(".keeplane-init-*.pending"))


def test_plan_write_failure_retains_named_plan_for_review(project, monkeypatch):
    root, plan = project
    before, original, failed = state(root), os.fsync, False

    def sync(descriptor):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("synthetic plan sync failure")
        return original(descriptor)

    monkeypatch.setattr(os, "fsync", sync)
    with pytest.raises(migration.MigrationError, match="not confirmed saved"):
        migration.review(root, "CLAUDE.md", plan)
    assert plan.exists() and state(root) == before
    assert "PRIVATE_RULE" not in plan.read_text()
    with pytest.raises(FileExistsError):
        migration.review(root, "CLAUDE.md", plan)
    fresh = plan.with_name("fresh.json")
    migration.review(root, "CLAUDE.md", fresh)
    migration.apply(root, fresh)


def test_failed_sync_preserves_a_user_permission_change(project, monkeypatch):
    root, plan = planned(project)
    original = os.fsync

    def sync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            (root / "AGENTS.md").chmod(0o644)
            raise OSError("synthetic sync failure")
        return original(descriptor)

    monkeypatch.setattr(os, "fsync", sync)
    with pytest.raises(migration.MigrationError, match="outcome needs review"):
        migration.apply(root, plan)
    assert stat.S_IMODE((root / "AGENTS.md").stat().st_mode) == 0o644
    assert (root / "AGENTS.md").read_bytes() == (root / "CLAUDE.md").read_bytes()
