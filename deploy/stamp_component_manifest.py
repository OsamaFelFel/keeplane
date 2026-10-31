"""Write a copy of the component manifest with the values known only at build time.

The committed deploy/component-manifest.json keeps these fields null. A build
that produces an image or chart package runs this script and keeps the output
with that build's results. Only the build section changes: app_image keeps
describing the chart's default reference.
"""

import argparse
import json
import re
import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "component-manifest.json"
COMMIT = re.compile(r"[0-9a-f]{40}")
IMAGE = re.compile(r"[a-z0-9.\-_/:]+@sha256:[0-9a-f]{64}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def stamp(manifest, *, commit, app_image, chart_digest=None):
    if not COMMIT.fullmatch(commit or ""):
        raise ValueError("The commit must be a full 40-character Git SHA")
    if not IMAGE.fullmatch(app_image or ""):
        raise ValueError("The app image must be repository@sha256:<digest>, not a tag")
    if chart_digest is not None and not DIGEST.fullmatch(chart_digest):
        raise ValueError("The chart digest must be sha256:<digest>")
    stamped = json.loads(json.dumps(manifest))
    stamped["build"].update(
        {
            "keeplane_commit": commit,
            "app_image_digest": app_image,
            "chart_package_digest": chart_digest,
        }
    )
    return stamped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", required=True, help="Full Git SHA that was built")
    parser.add_argument(
        "--app-image",
        required=True,
        help="Built app image as repository@sha256:<digest>",
    )
    parser.add_argument("--chart-digest", help="Packaged chart digest, sha256:<digest>")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.resolve() == MANIFEST:
        parser.error(
            "Write the stamped copy elsewhere; the committed manifest stays unstamped"
        )
    try:
        stamped = stamp(
            json.loads(MANIFEST.read_text()),
            commit=args.commit,
            app_image=args.app_image,
            chart_digest=args.chart_digest,
        )
    except ValueError as error:
        parser.error(str(error))
    args.output.write_text(json.dumps(stamped, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
