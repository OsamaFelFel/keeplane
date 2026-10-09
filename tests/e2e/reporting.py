"""Put repeatable test reports in a caller-selected directory when requested."""

import os
from pathlib import Path


def report_path(filename):
    default = Path(__file__).with_name("runs")
    directory = Path(os.environ.get("KEEPLANE_TEST_REPORT_DIR", default))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename
