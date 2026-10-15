"""Source verification refuses changed bytes and never evaluates recipes."""

import hashlib
import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

path = (
    Path(__file__).resolve().parents[2]
    / "components/control-plane/collect_runtime_sources.py"
)
spec = importlib.util.spec_from_file_location("runtime_sources", path)
sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)


def test_download_verifies_bytes_and_removes_failed_partial(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"source fixture")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/source"
    try:
        digest = hashlib.sha256(b"source fixture").hexdigest()
        good = sources.download(
            ("fixture", "good", "sha256", digest, [url]), tmp_path, sources.Budget()
        )
        bad = sources.download(
            ("fixture", "bad", "sha256", "0" * 64, [url]), tmp_path, sources.Budget()
        )
        assert good["verified"] and not bad["verified"]
        assert (tmp_path / "fixture/good").read_bytes() == b"source fixture"
        assert not (tmp_path / "fixture/bad").exists()
        assert not list(tmp_path.rglob("*.partial"))
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize(
    "record",
    [
        "SKIP source.tar.gz",
        "0" * 128 + " ../escape",
        "$(touch marker) file",
        "0" * 128 + " APKBUILD",
        "0" * 128 + " source.partial",
    ],
)
def test_recipe_records_reject_unsupported_shell_and_paths(record):
    with pytest.raises(ValueError):
        sources.source_tasks({"origin": "gdbm"}, f'sha512sums="\n{record}\n"', "v3.24")


def test_recipe_is_text_and_keeps_local_patch(tmp_path):
    marker = tmp_path / "never-created"
    recipe = {"origin": "readline", "url": "https://example.invalid/APKBUILD"}
    text = f'touch {marker}\nsha512sums="\n' + "a" * 128 + ' fix.patch\n"'
    task = sources.source_tasks(recipe, text, "v3.24")[0]
    assert task[1] == "fix.patch" and task[4][0].endswith("/fix.patch")
    assert not marker.exists()
    assert (
        sources.source_tasks(recipe, text.replace("fix.patch", "__stack.c"), "v3.24")[
            0
        ][1]
        == "__stack.c"
    )
    with pytest.raises(ValueError, match="Duplicate"):
        sources.source_tasks(
            recipe,
            text.replace("fix.patch\n", "fix.patch\n" + "a" * 128 + " fix.patch\n"),
            "v3.24",
        )


def test_budget_refuses_expired_download(tmp_path):
    budget = sources.Budget()
    budget.deadline = 0
    result = sources.download(
        ("fixture", "file", "sha256", "0" * 64, ["http://127.0.0.1:1/"]),
        tmp_path,
        budget,
    )
    assert not result["verified"] and "time limit" in result["errors"][0]


def test_existing_output_is_preserved(tmp_path):
    marker = tmp_path / "existing"
    marker.write_text("keep")
    pins = {"alpine_release": "v3.24", "recipes": [], "python": {"version": "3.13.16"}}
    with pytest.raises(FileExistsError):
        sources.collect(pins, tmp_path)
    assert marker.read_text() == "keep"


def test_duplicate_origins_are_rejected_before_writing(tmp_path):
    pins = {"alpine_release": "v3.24", "recipes": [{"origin": "gdbm"}] * 2}
    with pytest.raises(ValueError, match="Duplicate"):
        sources.collect(pins, tmp_path / "output")
    assert not (tmp_path / "output").exists()
