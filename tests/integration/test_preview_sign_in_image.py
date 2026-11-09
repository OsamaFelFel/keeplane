"""The default preview image carries CLI sign-in and its notices (task 009-01).

Case PSIMG-01 in preview-sign-in-image-cases.md. Live: needs Docker and the
image `python3 deploy/local/up.py` builds (keeplane-preview:docker-local), or
another image from the default `preview` target named in
KEEPLANE_PREVIEW_IMAGE. Nothing is installed or copied over its packages.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.live, pytest.mark.infrastructure]
IMAGE = os.environ.get("KEEPLANE_PREVIEW_IMAGE", "keeplane-preview:docker-local")


def test_psimg_01_the_preview_image_has_the_sign_in_packages_and_notices():
    found = subprocess.run(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if found.returncode:
        pytest.skip(
            f"Build the preview image first ({IMAGE}): python3 deploy/local/up.py"
        )
    probe = Path(__file__).resolve().parents[1] / "fixtures/preview_sign_in_probe.py"
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65532:65532",
            "--tmpfs",
            "/state:uid=65532,gid=65532,mode=0700",
            "--tmpfs",
            "/tmp:uid=65532,gid=65532,mode=0700",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "--mount",
            f"type=bind,src={probe},dst=/probe.py,readonly",
            "--entrypoint",
            "python",
            found.stdout.strip(),
            "/probe.py",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    observed = json.loads(result.stdout.splitlines()[-1])
    pins = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "components/control-plane/licenses/cli-auth-trial.json"
        ).read_text()
    )
    assert observed == {
        "uid": 65532,
        "database": "sqlite",
        "toolkit": "3.4.1",
        "packages": len(pins["packages"]),
        "notices": sum(len(item["notices"]) for item in pins["packages"]),
        "clients": ["keeplane-cli", "keeplane-cli-device"],
        "ready": True,
        "installers_absent": True,
    }
