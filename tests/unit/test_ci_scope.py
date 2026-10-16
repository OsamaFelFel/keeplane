"""Real Git changes and workflow failure behavior for documentation selection."""

import json
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
docs_only = runpy.run_path(ROOT / ".github/scripts/ci_scope.py")["docs_only"]


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.git("init", "--quiet")
        self.git("config", "user.email", "ci-fixture@example.invalid")
        self.git("config", "user.name", "CI fixture")
        self.git("config", "core.filemode", "true")
        for path in (
            "README.md",
            "components/cli/README.md",
            "docs/guide.md",
            "app.py",
        ):
            self.write(path)
        self.base = self.commit()

    def git(self, *arguments):
        return (
            subprocess.check_output(["git", *arguments], cwd=self.repo).decode().strip()
        )

    def write(self, path):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("updated documentation\n")
        target.chmod(0o644)

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "--allow-empty", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def selected(self, *, base=None, event_name="pull_request"):
        event = self.repo / "event.json"
        event.write_text(
            json.dumps(
                {
                    "pull_request": {
                        "base": {"sha": self.base if base is None else base},
                        "head": {"sha": self.git("rev-parse", "HEAD")},
                    }
                }
            )
        )
        return docs_only(event_name, event, directory=self.repo)

    def test_only_explicit_markdown_paths_skip(self):
        for path in ("README.md", "components/cli/README.md", "docs/guide.md"):
            (self.repo / path).write_text("human correction\n")
        self.write("docs/nested/new guide.md")
        self.commit()
        self.assertTrue(self.selected())

    def test_unknown_mixed_and_sensitive_paths_run_full(self):
        for path in (
            "app.py",
            "tests/cases.md",
            "licenses/notice.md",
            ".github/workflows/checks.yml",
            "docs/tool.py",
            "docs/data.json",
            "components/admin-ui/README.md",
            "unknown.md",
        ):
            with self.subTest(path=path):
                self.git("reset", "--hard", self.base)
                self.git("clean", "-fdq")
                self.write(path)
                (self.repo / path).write_text("changed application input\n")
                self.write("docs/also-added.md")
                self.commit()
                self.assertFalse(self.selected())

    def test_doc_deletion_and_rename_run_full(self):
        (self.repo / "docs/guide.md").rename(self.repo / "docs/moved.md")
        self.commit()
        self.assertFalse(self.selected())
        self.git("reset", "--hard", self.base)
        (self.repo / "components/cli/README.md").unlink()
        self.commit()
        self.assertFalse(self.selected())

    def test_file_mode_or_symlink_change_runs_full(self):
        (self.repo / "README.md").chmod(0o755)
        self.commit()
        self.assertFalse(self.selected())
        self.git("reset", "--hard", self.base)
        target = self.repo / "docs/link.md"
        target.symlink_to("../app.py")
        self.commit()
        self.assertFalse(self.selected())

    def test_empty_missing_base_and_untrusted_sha_run_full(self):
        self.assertFalse(self.selected())
        self.write("docs/new.md")
        self.commit()
        for base in ("f" * 40, "0" * 40, "HEAD", "--output=oops", None):
            with self.subTest(base=base):
                if base is None:
                    self.assertFalse(docs_only("pull_request", self.repo / "absent"))
                else:
                    self.assertFalse(self.selected(base=base))

    def test_main_manual_and_initial_push_always_run_full(self):
        self.write("docs/new.md")
        self.commit()
        for name in ("push", "workflow_dispatch", "pull_request_target", None):
            with self.subTest(event=name):
                self.assertFalse(self.selected(event_name=name, base="0" * 40))

    def test_unreadable_malformed_or_incomplete_event_runs_full(self):
        path = self.repo / "event.json"
        for value in ("invalid", "[]", "{}", '{"pull_request":null}', "x" * 65537):
            with self.subTest(value=value[:30]):
                path.write_text(value)
                self.assertFalse(docs_only("pull_request", path))

    def test_nul_paths_do_not_become_shell_arguments(self):
        self.write("docs/quoted ' name\n$(touch oops).md")
        self.commit()
        self.assertTrue(self.selected())
        self.assertFalse((self.repo / "oops").exists())


class WorkflowTests(unittest.TestCase):
    def test_existing_jobs_run_on_classifier_failure_or_unknown_output(self):
        workflow = ROOT / ".github/workflows/checks.yml"
        text = workflow.read_text()
        gate = "if: ${{ !cancelled() && (needs.scope.result != 'success' || needs.scope.outputs.docs_only != 'true') }}"
        for job in ("frontend", "backend", "local-application", "postgres"):
            self.assertIn("  " + job + ":\n    needs: scope\n    " + gate, text)
        self.assertNotIn("paths-ignore:", text)
        self.assertNotIn("pull_request_target:", text)


if __name__ == "__main__":
    unittest.main()
