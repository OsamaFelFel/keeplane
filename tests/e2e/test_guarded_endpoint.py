"""Exercise the protected provider through the real application network."""

import pytest
import json
from pathlib import Path
import subprocess


def test_guarded_provider_transport():
    root = Path(__file__).resolve().parents[2]
    source = (root / "tests/fixtures/guarded_probe.py").read_text()
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "app", "python", "-"],
        input=source,
        text=True,
        capture_output=True,
        cwd=root,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert {case.get("id", case.get("case")) for case in report["results"]} == {
        "LOCAL-12",
        "LOCAL-13",
        "LOCAL-14",
        "LOCAL-15",
    }
    assert all(case["verdict"] == "pass" for case in report["results"])


pytestmark = pytest.mark.docker_only
