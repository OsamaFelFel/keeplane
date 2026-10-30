"""Record release-secret gaps in the pinned local integration chart."""

import pytest

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from tests.support.helm import require_helm


ROOT = Path(__file__).resolve().parents[2]
HELM = require_helm()


def run_cases():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Evidence output already exists")
    rendered = subprocess.run(
        (
            HELM,
            "template",
            "keeplane",
            "deploy/helm/keeplane",
            "-f",
            "deploy/local/values.yaml",
        ),
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    ).stdout
    configmaps = [
        part for part in rendered.split("---\n") if "kind: ConfigMap\n" in part
    ]
    passwords = [
        match.group(1)
        for part in configmaps
        for match in re.finditer(r"postgres(?:ql)?://[^:\s\"']+:([^@\s\"']+)@", part)
    ]
    password_in_configmap = any(
        not re.fullmatch(r"\$\{[A-Z_][A-Z0-9_]*\}", password) for password in passwords
    )
    report = {
        "suite": "production packaging diagnostic",
        "chart_dependency": "agentgateway-standalone-v1.6.0",
        "cases": [
            {
                "case": "PKG-GAP-01",
                "release_expectation_passes": not password_in_configmap,
                "observed": {"password_in_rendered_configmap": password_in_configmap},
            }
        ],
        "release_package_approved": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run_cases())


def test_production_package_gaps(monkeypatch, report_file, request):
    arguments = [__file__, "--output", str(report_file)]
    monkeypatch.setattr("sys.argv", arguments)
    assert run_cases() in (None, 0)


pytestmark = [pytest.mark.live]
