"""Shared discovery markers; expensive infrastructure checks are explicit."""

from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
import os
import uuid
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--app-image",
        default=None,
        help="Packaged PostgreSQL application image for integration checks",
    )
    from tests.support.shards import NAMES

    parser.addoption(
        "--shard",
        choices=NAMES,
        default=None,
        help="Run only the unit and integration test files of one backend CI shard",
    )


def pytest_ignore_collect(collection_path, config):
    """Skip importing other shards' files while walking the test folders."""
    shard = config.getoption("shard")
    if not shard or not collection_path.is_file():
        return None
    from tests.support.shards import is_test_file, shard_of

    if is_test_file(collection_path) and shard_of(collection_path) not in (None, shard):
        return True
    return None


def select_shard(config, items):
    """Keep only the selected backend shard's files, explicit paths included."""
    shard = config.getoption("shard")
    if not shard:
        return
    from tests.support.shards import shard_of

    owners = {}
    for item in items:
        path = Path(str(item.path))
        if path not in owners:
            owners[path] = shard_of(path)
            if owners[path] is None:
                raise pytest.UsageError(
                    f"{path} belongs to no backend shard; --shard covers "
                    "tests/unit and tests/integration only"
                )
    other = [item for item in items if owners[Path(str(item.path))] != shard]
    if other:
        config.hook.pytest_deselected(items=other)
        items[:] = [item for item in items if owners[Path(str(item.path))] == shard]


def pytest_configure():
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    os.environ.setdefault(
        "KEEPLANE_TEST_REPORT_DIR",
        str(Path(__file__).resolve().parents[1] / "test-results/pytest" / run_id),
    )


def pytest_collection_modifyitems(config, items):
    select_shard(config, items)
    for item in items:
        parts = Path(str(item.path)).parts
        for kind in ("unit", "integration", "e2e"):
            if kind in parts:
                item.add_marker(getattr(pytest.mark, kind))
        if "e2e" in parts:
            item.add_marker(pytest.mark.live)


@pytest.fixture
def cli_browser_driver():
    """Use the HTTP form driver unless a rendered-browser case overrides it."""
    return None


@pytest.fixture
def domain_services(db, tmp_path):
    from accounts.services import DjangoIdentity
    from audit.services import DjangoAuditStore
    from data_classes.services import DjangoDataClassStore
    from model_registry.catalog import DjangoModelCatalog

    secret = tmp_path / "first-admin-password"
    secret.write_text("first-test-password-123\n")
    audit = DjangoAuditStore()
    return SimpleNamespace(
        audit=audit,
        identity=DjangoIdentity(secret, audit),
        secret=secret,
        classes=DjangoDataClassStore(audit),
        catalog=DjangoModelCatalog(audit),
    )


@pytest.fixture
def report_file(request):
    from tests.support.reporting import report_path

    return report_path(request.node.name + "-" + uuid.uuid4().hex[:8] + ".json")
