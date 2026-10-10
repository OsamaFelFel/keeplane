"""Record release-secret gaps in the pinned local integration chart."""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import os


ROOT = Path(__file__).resolve().parents[2]
HELM = os.environ.get("KEEPLANE_HELM_BIN") or shutil.which("helm") or "/private/tmp/keeplane-helm/darwin-amd64/helm"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Evidence output already exists")
    rendered = subprocess.run((HELM, "template", "keeplane", "deploy/helm/keeplane",
                               "-f", "deploy/local/values.yaml"), cwd=ROOT,
                              text=True, capture_output=True, timeout=30, check=True).stdout
    configmaps = [part for part in rendered.split("---\n") if "kind: ConfigMap\n" in part]
    password_in_configmap = any(re.search(r"postgres(?:ql)?://[^\s\"']+:[^\s\"']+@", part)
                                for part in configmaps)
    report = {"suite": "production packaging diagnostic", "chart_dependency": "agentgateway-standalone-v1.6.0",
              "cases": [{"case": "PKG-GAP-01", "release_expectation_passes": not password_in_configmap,
                         "observed": {"password_in_rendered_configmap": password_in_configmap}}],
              "release_package_approved": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
