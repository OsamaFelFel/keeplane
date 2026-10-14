"""Put repeatable test reports in a caller-selected directory when requested."""

import os
from pathlib import Path


def report_path(filename):
    default = Path(__file__).resolve().parents[2] / "test-results/e2e"
    directory = Path(os.environ.get("KEEPLANE_TEST_REPORT_DIR", default))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename
