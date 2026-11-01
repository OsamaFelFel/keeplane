"""Backend CI shards: each unit and integration test file runs in exactly one.

A shard owns the test files of one folder whose names sort from its first
bound (inclusive) up to its second (exclusive). Each folder's ranges start at
"" and end at None (no upper bound), so a new or renamed file always lands in
one shard and can never fall out of the backend checks. The CI matrix in
.github/workflows/checks.yml lists exactly these names; the unit test
tests/unit/test_backend_checks.py checks both.
"""

from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]

# (shard name, folder under tests/, file names from, file names before)
SHARDS = (
    ("unit", "unit", "", None),
    ("integration-a-to-l", "integration", "", "test_m"),
    ("integration-m-to-z", "integration", "test_m", None),
)
NAMES = tuple(name for name, _, _, _ in SHARDS)
FOLDERS = tuple(dict.fromkeys(folder for _, folder, _, _ in SHARDS))


def is_test_file(path):
    return path.name.startswith("test_") and path.suffix == ".py"


def shards_of(path):
    """Return every shard whose range holds this file (exactly one when sharded)."""
    try:
        relative = Path(path).resolve().relative_to(TESTS)
    except ValueError:
        return []
    if len(relative.parts) < 2:
        return []
    folder, name = relative.parts[0], relative.name
    return [
        shard
        for shard, owner, start, before in SHARDS
        if owner == folder and start <= name and (before is None or name < before)
    ]


def shard_of(path):
    """Return the one shard that runs this test file, or None outside the shards."""
    owners = shards_of(path)
    if len(owners) > 1:
        raise ValueError(f"{path} is in more than one backend shard: {owners}")
    return owners[0] if owners else None


def sharded_files():
    for folder in FOLDERS:
        yield from sorted(p for p in (TESTS / folder).rglob("*.py") if is_test_file(p))
