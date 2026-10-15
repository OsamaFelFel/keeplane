"""Optional exact-binary check; no live model or developer credentials."""

import os
from pathlib import Path
import tempfile
from threading import Thread
from unittest.mock import patch

if __name__ != "__main__":
    import pytest
    pytestmark = pytest.mark.optional

from components.cli.opencode_adapter import run
from tests.fixtures.cli_coding_provider import Handler, start


def native_turn(binary):
    class AuditedProfile(tempfile.TemporaryDirectory):
        def __exit__(self, *args):
            try:
                for path in Path(self.name).rglob("*"):
                    if path.is_file():
                        assert Handler.grant.encode() not in path.read_bytes(), path.name
            finally:
                super().__exit__(*args)

    with tempfile.TemporaryDirectory(prefix="keeplane-cli-project-") as temporary:
        project = Path(temporary)
        target = project / "math.py"
        target.write_text("def add(a, b):\n    return a - b\n")
        # A project provider override must not divert the configured gateway.
        (project / "opencode.json").write_text('{"providers":{"keeplane":{"settings":{"baseURL":"http://127.0.0.1:1/v1"}}}}')
        server = start(target)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("components.cli.opencode_adapter.tempfile.TemporaryDirectory", AuditedProfile):
                result = run(binary, project, f"http://127.0.0.1:{server.server_port}/v1",
                             "fixture-coder", "Fix the addition function in math.py.", Handler.grant, 60)
            assert result.returncode == 0, (result.stdout, result.stderr)
            assert target.read_text() == "def add(a, b):\n    return a + b\n"
            assert Handler.calls == ["read", "edit"]
            assert Handler.grant not in result.stdout + result.stderr
            denied = run(binary, project, f"http://127.0.0.1:{server.server_port}/v1",
                         "fixture-coder", "Change the function.", "invalid-test-grant", 30)
            assert denied.returncode != 0
            assert Handler.calls == ["read", "edit"]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def test_native_coding_turn():
    import pytest
    binary = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not binary:
        pytest.skip("Set KEEPLANE_OPENCODE_V2_BIN to the pinned local runtime.")
    native_turn(binary)


if __name__ == "__main__":
    native_turn(os.environ["KEEPLANE_OPENCODE_V2_BIN"])
