"""Compose the Django-backed services without touching storage during URL loading."""

import os
from functools import lru_cache
from accounts.services import DjangoIdentity
from audit.services import DjangoAuditStore
from data_classes.services import DjangoDataClassStore
from model_registry.catalog import DjangoModelCatalog
from .errors import StorageUnavailable


@lru_cache(maxsize=1)
def stores():
    password_file = os.environ.get("FIRST_ADMIN_PASSWORD_FILE")
    if not password_file:
        raise StorageUnavailable(
            "Configure the infrastructure admin before using the API"
        )
    audit = DjangoAuditStore()
    return (
        audit,
        DjangoIdentity(password_file, audit),
        DjangoModelCatalog(audit),
        DjangoDataClassStore(audit),
    )
