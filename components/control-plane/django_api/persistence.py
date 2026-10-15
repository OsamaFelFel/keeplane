"""Select one complete storage implementation; never mix transaction stores."""

from functools import lru_cache
import os


@lru_cache(maxsize=1)
def stores():
    if os.environ.get("KEEPLANE_DATABASE_HOST"):
        from django_api.accounts.audit import DjangoAuditStore
        from django_api.accounts.catalog import DjangoModelCatalog
        from django_api.accounts.data_classes import DjangoDataClassStore
        from django_api.accounts.identity import DjangoIdentity

        audit = DjangoAuditStore()
        return (audit, DjangoIdentity(os.environ["FIRST_ADMIN_PASSWORD_FILE"], audit),
                DjangoModelCatalog(audit), DjangoDataClassStore(audit))
    from audit import AuditStore
    from data_classes import DataClassStore
    from local_identity import LocalIdentity
    from model_catalog import ModelCatalog

    audit = AuditStore(os.environ["MODEL_APPROVAL_DB"])
    return (audit, LocalIdentity(os.environ["ACCOUNT_DB"], os.environ["FIRST_ADMIN_PASSWORD_FILE"], audit),
            ModelCatalog(os.environ["MODEL_APPROVAL_DB"], audit),
            DataClassStore(os.environ["MODEL_APPROVAL_DB"], audit))
