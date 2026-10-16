"""Native checks for explicitly supplied packaged runtime images."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("variant", ["preview", "postgres"])
def test_runtime_image(variant):
    image = os.environ.get(f"KEEPLANE_RUNTIME_{variant.upper()}_IMAGE")
    if not image:
        pytest.skip(f"Set KEEPLANE_RUNTIME_{variant.upper()}_IMAGE to a packaged image")
    probe = Path(__file__).resolve().parents[1] / "fixtures/runtime_image_probe.py"
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/state:uid=65532,gid=65532,mode=0700",
            "--tmpfs",
            "/tmp:uid=65532,gid=65532,mode=0700",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-v",
            f"{probe}:/probe.py:ro",
            "--entrypoint",
            "python",
            image,
            "/probe.py",
            variant,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


pytestmark = [pytest.mark.live, pytest.mark.infrastructure]
