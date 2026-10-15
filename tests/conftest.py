"""Shared discovery markers; expensive infrastructure checks are explicit."""

from pathlib import Path
from types import SimpleNamespace
import uuid
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--app-image",
        default=None,
        help="Packaged PostgreSQL application image for integration checks",
    )


def pytest_collection_modifyitems(items):
    for item in items:
        parts = Path(str(item.path)).parts
        for kind in ("unit", "integration", "e2e"):
            if kind in parts:
                item.add_marker(getattr(pytest.mark, kind))
        if "e2e" in parts:
            item.add_marker(pytest.mark.live)


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
