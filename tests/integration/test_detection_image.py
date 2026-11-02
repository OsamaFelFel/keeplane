"""Load the detector in a packaged detection image, offline and read-only.

Cases DI-01 and DI-02 in detection-image-cases.md. Live: needs Docker and images built
from the detection targets, named in KEEPLANE_RUNTIME_DETECTION_IMAGE and
KEEPLANE_RUNTIME_DETECTION_SIGN_IN_IMAGE.
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


# Each detection image and the licence inventories its packages must match.
INSTALLED_SETS = {
    "KEEPLANE_RUNTIME_DETECTION_IMAGE": ["personal-data-detection.json"],
    "KEEPLANE_RUNTIME_DETECTION_SIGN_IN_IMAGE": ["cli-auth-trial.json",
                                                 "personal-data-detection.json"],
}


@pytest.mark.parametrize("variable", sorted(INSTALLED_SETS))
def test_di_02_each_package_is_installed_once_at_its_recorded_version(variable):
    image = os.environ.get(variable)
    if not image:
        pytest.skip(f"Set {variable} to a detection image")
    probe = Path(__file__).resolve().parents[1] / "fixtures/installed_set_probe.py"
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--read-only",
         "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
         "-v", f"{probe}:/probe.py:ro", "--entrypoint", "python",
         image, "/probe.py", *INSTALLED_SETS[variable]],
        check=False, capture_output=True, text=True, timeout=120,
    )
    print(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
