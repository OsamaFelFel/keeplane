"""Collect the pinned optional sign-in trial's sources and original notices."""

import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from collect_runtime_sources import Budget, download

ROOT = Path(__file__).resolve().parent


def relative(value):
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("Unsafe artifact or notice path")
    return path


def check_requirements(pins, requirements):
    declared = {}
    for line in requirements.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        match = re.fullmatch(
            r"([\w-]+)==([\w.]+)((?: --hash=sha256:[a-f0-9]{64})+)", line
        )
        if not match:
            raise ValueError("Unsupported optional requirement")
        name = match[1].lower().replace("_", "-")
        if name in declared:
            raise ValueError("Duplicate optional requirement")
        declared[name] = (match[2], re.findall(r"sha256:([a-f0-9]{64})", match[3]))
    packages = pins["packages"]
    names = [package["name"].lower().replace("_", "-") for package in packages]
    if len(names) != len(set(names)) or set(names) != set(declared):
        raise ValueError("Optional requirement inventory changed")
    for package in packages:
        expected = declared.get(package["name"].lower().replace("_", "-"))
        if (
            not expected
            or expected[0] != package["version"]
            or package["wheel"]["sha256"] not in expected[1]
        ):
            raise ValueError("Optional requirement inventory changed")


def collect(pins, wheels, output, source_cache=None):
    # Verify every cache input before creating output or starting downloads.
    notices, tasks = [], []
    for package in pins["packages"]:
        origin = relative(package["name"])
        if len(origin.parts) != 1:
            raise ValueError("Invalid package name")
        artifact = package["wheel"]
        name = relative(artifact["file"])
        if len(name.parts) != 1:
            raise ValueError("Invalid wheel filename")
        if (wheels / name).stat().st_size > 64 * 1024 * 1024:
            raise ValueError("Wheel exceeds 64 MiB")
        data = (wheels / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
            raise ValueError("Wheel checksum mismatch: " + package["name"])
        with ZipFile(wheels / name) as wheel:
            for filename, digest in package["notices"].items():
                target = relative(filename)
                if wheel.getinfo(filename).file_size > 1024 * 1024:
                    raise ValueError("Notice exceeds 1 MiB")
                original = wheel.read(filename)
                if hashlib.sha256(original).hexdigest() != digest:
                    raise ValueError("Notice checksum mismatch")
                notices.append((origin / target, original))
        tasks.append((package["name"], package["source"]))
    tasks.extend(
        ("license-texts", artifact) for artifact in pins["supplemental_license_texts"]
    )
    for _, artifact in tasks:
        if len(relative(artifact["file"]).parts) != 1 or not re.fullmatch(
            r"[a-f0-9]{64}", artifact["sha256"]
        ):
            raise ValueError("Invalid source pin")
        if not artifact["url"].startswith("https://"):
            raise ValueError("Source URLs require HTTPS")
    output.mkdir(parents=True, exist_ok=False)
    for name, data in notices:
        target = output / "notices" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    budget = Budget()

    def obtain(task):
        origin, artifact = task
        urls = (
            [(source_cache / artifact["file"]).resolve().as_uri()]
            if source_cache
            else [artifact["url"]]
        )
        return download(
            (origin, artifact["file"], "sha256", artifact["sha256"], urls),
            output,
            budget,
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(obtain, tasks))
    report = {
        "artifacts_verified": all(item["verified"] for item in results),
        "wheel_packages_verified": len(pins["packages"]),
        "original_notice_files": len(notices),
        "sources_and_license_texts": results,
        "complete_native_inventory": False,
        "open_native_review": pins["open_native_review"],
        "archives_extracted": False,
        "packages_installed": False,
    }
    (output / "inventory.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-cache", type=Path, required=True)
    parser.add_argument(
        "--source-cache",
        type=Path,
        help="Flat offline cache of pinned source/license files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Fresh directory outside the repository",
    )
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(ROOT.parents[1]):
        parser.error("Keep source archives and reports outside the repository")
    pins = json.loads((ROOT / "licenses/cli-auth-trial.json").read_text())
    try:
        check_requirements(pins, (ROOT / "requirements-cli-auth.txt").read_text())
        report = collect(pins, args.wheel_cache, args.output, args.source_cache)
    except (OSError, ValueError, BadZipFile, KeyError) as error:
        parser.error(str(error))
    print(
        "Verified optional artifacts; native review remains open."
        if report["artifacts_verified"]
        else "Artifact collection failed; see inventory.json."
    )
    return 0 if report["artifacts_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
