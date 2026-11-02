"""A package pinned in two requirement files of one image target pins one wheel.

Cases IRP-01 and IRP-02 in image-requirement-pins-cases.md. Optional sets
are installed with --ignore-installed into a prefix and copied over each
other, so two pins of one package in one image would leave two versions
installed and the licence inventories describing only one of them.
"""

import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "components" / "control-plane"
DOCKERFILE = (ROOT / "Dockerfile").read_text()
# Helpers that install a requirement set without naming its file here.
INDIRECT = {"package_postgres.py": "requirements-postgres.txt"}


def stages():
    """{stage: (base, body)} in Dockerfile order."""
    found = {}
    parts = re.split(r"^FROM ", DOCKERFILE, flags=re.M)[1:]
    for part in parts:
        header, _, body = part.partition("\n")
        base, _, name = header.partition(" AS ")
        found[name.strip()] = (base.strip(), body)
    return found


def requirement_files(stage, all_stages, seen=None):
    """Every requirement file installed in a stage, its base or a stage it copies."""
    seen = set() if seen is None else seen
    if stage in seen or stage not in all_stages:
        return set()
    seen.add(stage)
    base, body = all_stages[stage]
    files = set(re.findall(r"requirements-[\w-]+\.txt", body))
    files |= {name for helper, name in INDIRECT.items() if helper in body}
    sources = {base} | set(re.findall(r"--from=(\S+)", body))
    for source in sources:
        files |= requirement_files(source, all_stages, seen)
    return files


def pins(name):
    """{package: (version or URL, sorted hashes)} from one requirement file."""
    found = {}
    for line in (ROOT / name).read_text().splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)(?:==(\S+)| @ (\S+))", line)
        if match:
            package = match[1].lower().replace("_", "-")
            found[package] = (match[2] or match[3],
                              tuple(sorted(re.findall(r"--hash=sha256:([a-f0-9]{64})", line))))
    return found


# IRP-01 Each image target's requirement sets agree on every shared package.
def test_irp_01_shared_packages_in_one_image_target_pin_one_wheel():
    all_stages = stages()
    problems, shared = [], defaultdict(set)
    for stage in all_stages:
        by_package = defaultdict(dict)
        for name in sorted(requirement_files(stage, all_stages)):
            for package, pin in pins(name).items():
                by_package[package][name] = pin
        for package, found in by_package.items():
            if len(found) > 1:
                shared[stage].add(package)
                versions = {version for version, _ in found.values()}
                hashed = [set(hashes) for _, hashes in found.values() if hashes]
                # One version, and the hashed files share the wheel they allow
                # (a file may also allow another platform's wheel).
                if len(versions) > 1 or (hashed and not set.intersection(*hashed)):
                    problems.append(f"{stage}: {package} {found}")
    assert not problems, problems
    # The check sees the sets the detection targets combine.
    assert "certifi" in shared["postgres-cli-auth-detection"]
    assert requirement_files("postgres-cli-auth-detection", all_stages) == {
        "requirements-account-api.txt", "requirements-postgres.txt",
        "requirements-cli-auth.txt", "requirements-detection.txt"}


# IRP-02 Shared packages are recorded the same way in both licence inventories.
def test_irp_02_shared_packages_have_the_same_inventory_record():
    import json

    def rows(name):
        data = json.loads((ROOT / "licenses" / name).read_text())
        return {row["name"].lower().replace("_", "-"): row for row in data["packages"]}

    sign_in, detection = rows("cli-auth-trial.json"), rows("personal-data-detection.json")
    common = set(sign_in) & set(detection)
    assert "certifi" in common
    sign_in_pins = pins("requirements-cli-auth.txt")
    detection_pins = pins("requirements-detection.txt")
    for package in common:
        assert sign_in[package] == detection[package], package
        # The recorded wheel is the one both requirement files allow.
        wheel = sign_in[package]["wheel"]["sha256"]
        assert wheel in sign_in_pins[package][1], package
        assert wheel in detection_pins[package][1], package
