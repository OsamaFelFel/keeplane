"""Run the real shell launcher with isolated commands; never start a cluster."""

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("missing", "node_version", "docker_ready", "message", "calls"),
    [
        ("custom-helm", "v22.12.0", True, "Missing tool: custom-helm", []),
        (None, "v22.11.0", True, "Node.js 22.12 or newer is required", ["node"]),
        (None, "invalid-version", True, "Node.js 22.12 or newer is required", ["node"]),
        (None, "v22.12.0", False, "Docker is unavailable", ["node", "docker"]),
        (None, "v24.0.0", True, "Missing models/", ["node", "docker"]),
    ],
    ids=["missing-helm", "old-node", "invalid-node", "stopped-docker", "prerequisites-pass"],
)
def test_kind_startup_checks_prerequisites_before_model_or_state_work(
    tmp_path, missing, node_version, docker_ready, message, calls
):
    root = tmp_path / "repo"
    launcher = root / "deploy/local/kind-up.sh"
    launcher.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "deploy/local/kind-up.sh"
    runtime = tmp_path / "runtime"
    content = source.read_text()
    original = "RUNTIME_DIR=/private/tmp/keeplane-accounts-trial"
    assert content.count(original) == 1
    launcher.write_text(content.replace(original, "RUNTIME_DIR=" + shlex.quote(str(runtime))))
    commands = tmp_path / "bin"
    commands.mkdir()
    (commands / "dirname").symlink_to(shutil.which("dirname"))
    (commands / "python3").symlink_to(sys.executable)
    log = tmp_path / "commands.txt"
    for name in ("node", "npm", "docker", "kind", "kubectl", "custom-helm", "rg", "shasum"):
        if name == missing:
            continue
        script = commands / name
        content = '#!/bin/sh\nprintf "%s\\n" ' + shlex.quote(name) + ' >> "$KEEPLANE_CHECK_CALLS"\n'
        if name == "node":
            content += 'printf "%s\\n" ' + shlex.quote(node_version) + "\n"
        elif name == "docker" and docker_ready:
            content += "exit 0\n"
        else:
            content += "exit 1\n"
        script.write_text(content)
        script.chmod(0o755)
    result = subprocess.run(
        ["/bin/sh", str(launcher)],
        check=False, cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PATH": str(commands), "KEEPLANE_HELM_BIN": "custom-helm",
             "KEEPLANE_CHECK_CALLS": str(log)},
    )
    assert result.returncode == 1
    assert message in result.stderr
    assert "Traceback" not in result.stderr
    if message != "Missing models/":
        assert "Missing models/" not in result.stderr
    assert (log.read_text().splitlines() if log.exists() else []) == calls
    assert not runtime.exists()
    assert sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()) == [
        "deploy/local/kind-up.sh",
    ]
