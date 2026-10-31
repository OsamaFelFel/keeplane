"""Write a copy of the component manifest with the values known only at build time.

The committed deploy/component-manifest.json keeps these fields null. A build
that produces an image or chart package runs this script and keeps the output
with that build's results. Only the build section changes: app_image keeps
describing the chart's default reference.

With --check, the script instead reads a stamped copy and refuses it unless its
build fields are filled in with the expected values and every other section
still equals the committed manifest.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "component-manifest.json"
COMMIT = re.compile(r"[0-9a-f]{40}")
IMAGE = re.compile(r"[a-z0-9.\-_/:]+@sha256:[0-9a-f]{64}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
BUILD_FIELDS = ("keeplane_commit", "app_image_digest", "chart_package_digest")


def stamp(manifest, *, commit, app_image, chart_digest=None):
    """Return a copy of the manifest with the build section filled in.

    app_image is either a registry reference (repository@sha256:<digest>) or,
    for an image that was built but not pushed, its local image ID
    (sha256:<digest>). Tags are refused because they can move.
    """
    if not COMMIT.fullmatch(commit or ""):
        raise ValueError("The commit must be a full 40-character Git SHA")
    if not (IMAGE.fullmatch(app_image or "") or DIGEST.fullmatch(app_image or "")):
        raise ValueError(
            "The app image must be repository@sha256:<digest> or a local image ID "
            "sha256:<digest>, not a tag"
        )
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


def chart_metadata(text):
    """Read the top-level name, version and appVersion from a Chart.yaml."""
    found = {}
    for line in text.splitlines():
        match = re.match(r"(name|version|appVersion):\s*(.*?)\s*$", line)
        if match and match.group(1) not in found:
            value = match.group(2)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            found[match.group(1)] = value
    return found


def chart_package_digest(path, manifest):
    """Return sha256:<digest> of a packaged chart after checking it is this chart."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"No chart package at {path}")
    chart = manifest["chart"]
    try:
        with tarfile.open(path, "r:gz") as bundle:
            member = bundle.extractfile(chart["name"] + "/Chart.yaml")
            text = member.read().decode() if member else ""
    except (tarfile.TarError, KeyError, OSError, UnicodeDecodeError) as error:
        raise ValueError(f"{path} is not a packaged {chart['name']} chart") from error
    packaged = chart_metadata(text)
    expected = {
        "name": chart["name"],
        "version": chart["version"],
        "appVersion": chart["app_version"],
    }
    if packaged != expected:
        raise ValueError(
            f"{path} packages chart {packaged}, but the manifest records {expected}"
        )
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def local_image_id(reference, docker="docker"):
    """Return the local Docker image ID (sha256:<digest>) for a built image."""
    try:
        result = subprocess.run(
            (docker, "image", "inspect", "--format", "{{.Id}}", reference),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"Could not run {docker} to inspect {reference}") from error
    image_id = result.stdout.strip()
    if result.returncode or not DIGEST.fullmatch(image_id):
        raise ValueError(
            f"Docker has no built image {reference}: "
            + (result.stderr.strip() or image_id or "no image ID returned")
        )
    return image_id


def check(stamped, manifest, *, commit, app_image, chart_digest=None):
    """Refuse a stamped copy that is unstamped, mismatched or edited elsewhere."""
    problems = []
    build = stamped.get("build")
    if not isinstance(build, dict):
        build = {}
    expected = {
        "keeplane_commit": commit,
        "app_image_digest": app_image,
        "chart_package_digest": chart_digest,
    }
    for field in BUILD_FIELDS:
        value = build.get(field)
        if value is None and expected[field] is not None:
            problems.append(f"build.{field} is not stamped")
        elif value != expected[field]:
            problems.append(
                f"build.{field} is {value!r}, but this build produced "
                f"{expected[field]!r}"
            )
    unstamped = {k: v for k, v in build.items() if k not in BUILD_FIELDS}
    if unstamped != {
        k: v for k, v in manifest["build"].items() if k not in BUILD_FIELDS
    }:
        problems.append("build has fields the committed manifest does not")
    changed = sorted(
        key
        for key in set(stamped) | set(manifest)
        if key != "build" and stamped.get(key) != manifest.get(key)
    )
    if changed:
        problems.append(
            "these sections differ from the committed manifest: " + ", ".join(changed)
        )
    if problems:
        raise ValueError("; ".join(problems))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", required=True, help="Full Git SHA that was built")
    image = parser.add_mutually_exclusive_group(required=True)
    image.add_argument(
        "--app-image",
        help="Built app image as repository@sha256:<digest> or local ID sha256:<digest>",
    )
    image.add_argument(
        "--app-image-from-docker",
        metavar="REFERENCE",
        help="Local image tag to look up with docker image inspect",
    )
    chart = parser.add_mutually_exclusive_group()
    chart.add_argument("--chart-digest", help="Packaged chart digest, sha256:<digest>")
    chart.add_argument(
        "--chart-package",
        type=Path,
        help="Chart package (.tgz) from helm package; its SHA-256 is recorded",
    )
    parser.add_argument("--docker", default="docker", help=argparse.SUPPRESS)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="Where to write the stamped copy")
    mode.add_argument(
        "--check",
        type=Path,
        metavar="STAMPED",
        help="Check an existing stamped copy against this build instead of writing",
    )
    args = parser.parse_args(argv)
    if args.output and args.output.resolve() == MANIFEST:
        parser.error(
            "Write the stamped copy elsewhere; the committed manifest stays unstamped"
        )
    manifest = json.loads(MANIFEST.read_text())
    try:
        app_image = args.app_image or local_image_id(
            args.app_image_from_docker, args.docker
        )
        chart_digest = args.chart_digest
        if args.chart_package:
            chart_digest = chart_package_digest(args.chart_package, manifest)
        if args.check:
            try:
                stamped = json.loads(args.check.read_text())
            except (OSError, ValueError) as error:
                raise ValueError(f"Could not read {args.check} as JSON") from error
            if not isinstance(stamped, dict):
                raise ValueError(f"{args.check} is not a manifest")
            check(
                stamped,
                manifest,
                commit=args.commit,
                app_image=app_image,
                chart_digest=chart_digest,
            )
            print(
                f"{args.check} matches commit {args.commit}, image {app_image}"
                + (f", chart {chart_digest}" if chart_digest else "")
            )
            return 0
        stamped = stamp(
            manifest,
            commit=args.commit,
            app_image=app_image,
            chart_digest=chart_digest,
        )
    except ValueError as error:
        parser.error(str(error))
    args.output.write_text(json.dumps(stamped, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
