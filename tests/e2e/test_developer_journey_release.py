"""Task 009-15: the developer journey on release installs, in both gateway modes.

Runs the journey's DEV-01 to DEV-08 cases (test_developer_journey.py, with
DEV-03b, the request settings of DEV-03's task) on two disposable Docker
installs from tests/fixtures/release_journey.py, each on PostgreSQL with two
app copies behind one address:

- ``existing``: the customer's own agentgateway, set up as the gateway guide
  says, which asks Keeplane's checks before every model call;
- ``managed``: the managed gateway with the runtime installer and the model
  enroller, as in the Docker preview.

Each install has its own Compose project and loopback ports, so the local
preview and other projects are never touched. The coding cases need the
pinned runtime in ``KEEPLANE_OPENCODE_V2_BIN``, as for the preview journey;
without it they are recorded as not run and the test is skipped, so CI fails.
See developer-journey-release-cases.md.
"""

import json
import os
import shutil
import subprocess

import pytest

from tests.e2e import test_developer_journey as journey
from tests.fixtures.release_journey import COPIES, MODES, ROOT, ReleaseInstall
from tests.support.reporting import report_path

pytestmark = [pytest.mark.live, pytest.mark.infrastructure]

APP_IMAGE = os.environ.get(
    "KEEPLANE_SIGN_IN_POSTGRES_IMAGE", "keeplane-preview:postgres-cli-auth-local"
)
# The release journey's cases (developer-journey-release-cases.md): each runs
# CASES on one install.
INSTALLS = {"DJR-01": "existing", "DJR-02": "managed"}
CASES = (
    "DEV-01",
    "DEV-02",
    "DEV-03",
    "DEV-03b",
    "DEV-04",
    "DEV-05",
    "DEV-06",
    "DEV-07",
    "DEV-08",
)


assert tuple(INSTALLS.values()) == MODES


def unavailable_reason():
    """Why this machine can't start the release installs, or None."""
    if not shutil.which("docker") or not shutil.which("openssl"):
        return "Docker and openssl are needed for the disposable release installs."
    images = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())["images"]
    for image in (
        APP_IMAGE,
        images["agentgateway"],
        images["postgres"],
        images["python_fixture"],
    ):
        found = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if found.returncode:
            return (
                f"{image} is not on this machine. Build the app image with "
                "`docker build --target postgres-cli-auth-trial -t "
                "keeplane-preview:postgres-cli-auth-local "
                "-f components/control-plane/Dockerfile .` and pull the locked images."
            )
    ui = os.environ.get("KEEPLANE_ADMIN_UI_DIR", ROOT / "components/admin-ui")
    if not (ROOT / ui / "dist/index.html").is_file():
        return "Build the admin UI first: `npm ci && npm run build` in components/admin-ui."
    return None


@pytest.mark.parametrize("mode", list(INSTALLS.values()), ids=list(INSTALLS.values()))
def test_developer_journey_release(mode):
    reason = unavailable_reason()
    if reason:
        pytest.skip(reason)
    report_file = report_path(f"developer-journey-release-{mode}.json")
    with ReleaseInstall(mode, APP_IMAGE) as install:
        report = journey.run_cases(install, CASES, report_file)
        served = install.copies_served()
        problems = install.logs() if report["failed"] else ""
    # Both copies did the work behind the one address.
    report["copies_served"] = served
    report_file.write_text(json.dumps(report, indent=2) + "\n")
    print("copies served", json.dumps(served))
    assert [case["id"] for case in report["cases"]] == list(CASES)
    assert report["failed"] == 0 and report["cleanup"] == "complete", problems
    assert served and all(served.get(copy, 0) > 0 for copy in COPIES), served
    if report["not_run"]:
        pytest.skip("Not run: " + ", ".join(report["not_run"]))
