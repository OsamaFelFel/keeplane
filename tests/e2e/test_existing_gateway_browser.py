"""Run the React browser cases through the protected customer-run gateway app."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from kind_port_forward import BASE, existing_app


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = args.output.resolve()
    if report.exists():
        parser.error("Browser evidence already exists; choose a new run filename")
    report.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["KEEPLANE_BASE_URL"] = BASE
    with existing_app(), report.open("w") as output:
        result = subprocess.run(
            ["./node_modules/.bin/playwright", "test", "--reporter=json", "--workers=1"],
            cwd=ROOT / "tests/browser", env=environment, stdout=output, timeout=120)
    stats = json.loads(report.read_text())["stats"]
    print(json.dumps({"expected": stats["expected"], "unexpected": stats["unexpected"],
                      "flaky": stats["flaky"], "exit_code": result.returncode,
                      "report": str(report)}, indent=2))
    return int(result.returncode != 0 or stats["unexpected"] != 0 or stats["flaky"] != 0)


if __name__ == "__main__":
    sys.exit(main())
