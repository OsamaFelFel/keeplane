"""Backend CI shards cover every test file once; test hashing keeps the app format."""

import re
import subprocess
import sys
from pathlib import Path

import config.settings as application_settings
from django.conf import settings
from django.contrib.auth.hashers import (
    PBKDF2PasswordHasher,
    check_password,
    get_hasher,
    make_password,
)

from tests.support import shards
from tests.support.password_hashing import LowRoundPBKDF2PasswordHasher

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/checks.yml").read_text()


def test_bc01_every_test_file_is_in_exactly_one_shard():
    files = list(shards.sharded_files())
    assert any(path.parent.name == "integration" for path in files)
    for path in files:
        assert len(shards.shards_of(path)) == 1, path


def test_bc02_each_folders_ranges_follow_on_without_gap_or_overlap():
    for folder in shards.FOLDERS:
        ranges = [(start, before) for _, owner, start, before in shards.SHARDS if owner == folder]
        assert ranges[0][0] == "" and ranges[-1][1] is None, folder
        for (_, before), (start, _) in zip(ranges, ranges[1:]):
            assert before == start, folder
    for name in ("test_0.py", "test_a.py", "test_l.py", "test_m.py", "test_zz.py"):
        for folder in shards.FOLDERS:
            assert shards.shard_of(shards.TESTS / folder / "nested" / name)


def test_bc03_no_shard_runs_empty():
    owners = {shards.shard_of(path) for path in shards.sharded_files()}
    assert owners == set(shards.NAMES)


def test_bc04_ci_matrix_lists_exactly_the_shards():
    job = re.search(r"^  backend-tests:\n(.*?)(?=^  \S|\Z)", WORKFLOW, re.M | re.S)
    assert job, "backend-tests job is missing from checks.yml"
    matrix = re.search(r"^        shard: \[(.*)\]$", job.group(1), re.M)
    assert matrix, "backend-tests has no shard matrix"
    assert tuple(n.strip() for n in matrix.group(1).split(",")) == shards.NAMES
    assert '--shard "$SHARD"' in job.group(1)
    assert "tests/unit tests/integration" in job.group(1)


def collect(*arguments):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_bc05_shard_option_skips_other_files_and_refuses_unsharded_ones():
    unit_file = "tests/unit/test_backend_checks.py"
    owned = collect("--shard", "unit", unit_file)
    assert owned.returncode == 0 and "test_bc05" in owned.stdout, owned.stdout + owned.stderr
    other = collect("--shard", "integration-m-to-z", unit_file)
    assert other.returncode == 5 and "test_bc05" not in other.stdout, other.stdout
    e2e = sorted((ROOT / "tests/e2e").rglob("test_*.py"))[0]
    outside = collect("--shard", "unit", str(e2e.relative_to(ROOT)))
    assert outside.returncode == 4, outside.stdout + outside.stderr
    assert "belongs to no backend shard" in outside.stdout + outside.stderr


def test_bc06_test_hashes_keep_the_application_algorithm_and_format():
    assert application_settings.PASSWORD_HASHERS == [
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
        "accounts.hashers.PreviewScryptHasher",
    ]
    assert settings.PASSWORD_HASHERS[1:] == application_settings.PASSWORD_HASHERS[1:]
    test_hasher = get_hasher("default")
    assert isinstance(test_hasher, LowRoundPBKDF2PasswordHasher)
    assert test_hasher.algorithm == PBKDF2PasswordHasher.algorithm
    assert test_hasher.iterations < PBKDF2PasswordHasher.iterations

    from_tests = make_password("synthetic-password")
    assert from_tests.startswith("pbkdf2_sha256$")
    assert PBKDF2PasswordHasher().verify("synthetic-password", from_tests)
    from_application = PBKDF2PasswordHasher().encode("synthetic-password", "fixedsalt" * 2)
    assert check_password("synthetic-password", from_application)
    assert not check_password("another-password", from_application)
