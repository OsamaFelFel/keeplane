"""Load the detector in a packaged detection image, offline and read-only.

Case DI-01 in detection-image-cases.md. Live: needs Docker and an image built
from a detection target, named in KEEPLANE_RUNTIME_DETECTION_IMAGE.
"""

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.live, pytest.mark.infrastructure]


def test_di_01_detector_loads_offline_on_a_read_only_root_within_1gi():
    image = os.environ.get("KEEPLANE_RUNTIME_DETECTION_IMAGE")
    if not image:
        pytest.skip("Set KEEPLANE_RUNTIME_DETECTION_IMAGE to a detection image")
    probe = Path(__file__).resolve().parents[1] / "fixtures/detection_image_probe.py"
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "--network", "none",
            "--read-only",
            # The chart's smallest accepted memory limit, with no swap.
            "--memory", "1g", "--memory-swap", "1g",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "-v", f"{probe}:/probe.py:ro",
            "--entrypoint", "python",
            image, "/probe.py",
        ],
        check=False, capture_output=True, text=True, timeout=600,
    )
    print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
