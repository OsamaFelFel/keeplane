"""Collect the pinned optional sign-in trial's sources and original notices."""

import argparse
import hashlib
import json
import re
import tarfile
import tomllib
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


def rust_components(pins, records):
    inventory = pins.get("rust_inventory")
    if not inventory:
        return []
    declared = inventory["declared_by"]
    sbom = json.loads(records[(declared["package"], declared["member"])])
    registry = [
        row
        for row in sbom["components"]
        if row["bom-ref"].startswith(
            "registry+https://github.com/rust-lang/crates.io-index#"
        )
    ]
    selected = inventory["registry_components"]
    identity = lambda row: (row["name"], row["version"])
    if len({identity(row) for row in selected}) != len(selected) or {
        identity(row) for row in selected
    } != {identity(row) for row in registry}:
        raise ValueError("Rust registry inventory does not match the wheel SBOM")
    for row in selected:
        match = next(item for item in registry if identity(item) == identity(row))
        name, version = row["name"], row["version"]
        if (
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", version)
            or row["scope"] != match.get("scope")
            or row["licenses"] != match.get("licenses")
            or match.get("purl") != f"pkg:cargo/{name}@{version}"
            or {"alg": "SHA-256", "content": row["source"]["sha256"]}
            not in match.get("hashes", [])
            or row["source"]["file"] != f"{name}-{version}.crate"
            or row["source"]["url"]
            != f"https://static.crates.io/crates/{name}/{name}-{version}.crate"
            or not row["source_notices"]
        ):
            raise ValueError("Rust source does not match the wheel SBOM")
        for filename in row["source_notices"]:
            relative(filename)
    fields = ("name", "version", "scope", "licenses")
    workspace = [
        {field: row[field] for field in fields}
        for row in sbom["components"]
        if row not in registry
    ]
    if sorted(workspace, key=identity) != sorted(
        inventory["workspace_components"], key=identity
    ):
        raise ValueError("Rust workspace inventory does not match the wheel SBOM")
    return selected


def original_members(path, members):
    pending = []
    with tarfile.open(path, "r:gz") as archive:
        for filename, digest in members.items():
            relative(filename)
            member = archive.getmember(filename)
            if not member.isfile() or member.size > 1024 * 1024:
                raise ValueError("Source notice must be a bounded regular file")
            original = archive.extractfile(member).read()
            if hashlib.sha256(original).hexdigest() != digest:
                raise ValueError("Source notice checksum mismatch")
            pending.append((relative(filename), original))
    return pending


def rust_lock(pins, output, crates):
    inventory = pins["rust_inventory"]
    lock = inventory["cargo_lock"]
    package = next(row for row in pins["packages"] if row["name"] == lock["package"])
    original = original_members(
        output / package["name"] / package["source"]["file"],
        {lock["member"]: lock["sha256"]},
    )[0][1]
    rows = tomllib.loads(original.decode())["package"]
    identity = lambda row: (row["name"], row["version"])
    declared = inventory["declared_by"]
    sbom = json.loads(
        (
            output / "build-records" / declared["package"] / declared["member"]
        ).read_text()
    )
    expected = {
        *map(identity, crates),
        *map(identity, inventory["workspace_components"]),
        identity(sbom["metadata"]["component"]),
    }
    if (
        len({identity(row) for row in rows}) != len(rows)
        or {identity(row) for row in rows} != expected
    ):
        raise ValueError("Cargo lock package inventory changed")
    for crate in crates:
        match = next(row for row in rows if identity(row) == identity(crate))
        if match.get("checksum") != crate["source"]["sha256"] or match.get(
            "source"
        ) != ("registry+https://github.com/rust-lang/crates.io-index"):
            raise ValueError("Cargo lock crate checksum changed")
    for row in rows:
        if identity(row) not in {identity(crate) for crate in crates} and (
            row.get("source") or row.get("checksum")
        ):
            raise ValueError("Cargo workspace source changed")
    target = output / "build-records" / lock["package"] / lock["member"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(original)


def collect(pins, wheels, output, source_cache=None):
    # Verify every cache input before creating output or starting downloads.
    notices, tasks, build_records = [], [], {}
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
            for filename, digest in package.get("build_records", {}).items():
                relative(filename)
                if wheel.getinfo(filename).file_size > 1024 * 1024:
                    raise ValueError("Build record exceeds 1 MiB")
                original = wheel.read(filename)
                if hashlib.sha256(original).hexdigest() != digest:
                    raise ValueError("Build record checksum mismatch")
                build_records[(package["name"], filename)] = original
        tasks.append((package["name"], package["source"]))
    tasks.extend(
        ("license-texts", artifact) for artifact in pins["supplemental_license_texts"]
    )
    crates = rust_components(pins, build_records)
    tasks.extend(("rust-" + row["name"], row["source"]) for row in crates)
    for native in pins.get("native_sources", []):
        if len(relative(native["name"]).parts) != 1:
            raise ValueError("Invalid native component name")
        declared = native["declared_by"]
        record = json.loads(build_records[(declared["package"], declared["member"])])
        matches = [
            component
            for component in record["components"]
            if component["name"] == native["name"]
            and component.get("version") == native["version"]
        ]
        if (
            len(matches) != 1
            or {"alg": "SHA-256", "content": native["source"]["sha256"]}
            not in matches[0].get("hashes", [])
            or {"type": "distribution", "url": native["source"]["url"]}
            not in matches[0].get("externalReferences", [])
        ):
            raise ValueError("Native source does not match the wheel SBOM")
        for filename in native["source_notices"]:
            relative(filename)
        tasks.append((native["name"], native["source"]))
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
    for (package, filename), data in build_records.items():
        target = output / "build-records" / package / filename
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
    source_notices, failures = [], []
    accepted = {(item["origin"], item["name"]) for item in results if item["verified"]}
    cargo_verified = False
    if crates:
        try:
            rust_lock(pins, output, crates)
            cargo_verified = True
        except (OSError, ValueError, KeyError, tarfile.TarError) as error:
            failures.append(
                {"component": "rust-cargo-lock", "error_class": type(error).__name__}
            )
    for native in pins.get("native_sources", []):
        if (native["name"], native["source"]["file"]) not in accepted:
            continue
        try:
            source_notices.extend(
                (relative(native["name"]) / name, original)
                for name, original in original_members(
                    output / native["name"] / native["source"]["file"],
                    native["source_notices"],
                )
            )
        except (OSError, ValueError, KeyError, tarfile.TarError) as error:
            failures.append(
                {"component": native["name"], "error_class": type(error).__name__}
            )
    rust_notice_count = 0
    if cargo_verified:
        for crate in crates:
            origin = "rust-" + crate["name"]
            if (origin, crate["source"]["file"]) not in accepted:
                continue
            try:
                members = original_members(
                    output / origin / crate["source"]["file"], crate["source_notices"]
                )
                with tarfile.open(
                    output / origin / crate["source"]["file"], "r:gz"
                ) as archive:
                    entry = archive.getmember(
                        f"{crate['name']}-{crate['version']}/Cargo.toml"
                    )
                    if not entry.isfile() or entry.size > 1024 * 1024:
                        raise ValueError(
                            "Cargo manifest must be a bounded regular file"
                        )
                    package = tomllib.loads(archive.extractfile(entry).read().decode())[
                        "package"
                    ]
                    if (
                        package["name"] != crate["name"]
                        or package["version"] != crate["version"]
                        or package.get("license") != crate["source_manifest_license"]
                    ):
                        raise ValueError("Cargo manifest changed")
                source_notices.extend(
                    (relative(origin) / name, original) for name, original in members
                )
                rust_notice_count += len(members)
            except (OSError, ValueError, KeyError, tarfile.TarError) as error:
                failures.append(
                    {"component": origin, "error_class": type(error).__name__}
                )
    for name, data in source_notices:
        target = output / "notices" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    report = {
        "artifacts_verified": all(item["verified"] for item in results)
        and not failures,
        "wheel_packages_verified": len(pins["packages"]),
        "original_notice_files": len(notices),
        "original_build_records": len(build_records),
        "source_notice_files": len(source_notices),
        "native_source_records": pins.get("native_sources", []),
        "native_notice_failures": failures,
        "rust_inventory": pins.get("rust_inventory"),
        "rust_cargo_lock_verified": cargo_verified,
        "rust_source_notice_files": rust_notice_count,
        "sources_and_license_texts": results,
        "complete_native_inventory": False,
        "open_native_review": pins["open_native_review"],
        "archive_trees_unpacked": False,
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
