"""Translate database failures and serialize low-volume settings mutations."""

from contextlib import contextmanager
from functools import wraps

from django.db import DatabaseError, transaction

from common.errors import StorageUnavailable
from data_classes.models import Settings


def storage_service(cls):
    """Translate database failures into application storage errors."""
    for name, method in list(vars(cls).items()):
        if callable(method) and (not name.startswith("_") or name == "__init__"):

            @wraps(method)
            def guarded(*args, _method=method, **kwargs):
                try:
                    return _method(*args, **kwargs)
                except DatabaseError as error:
                    raise StorageUnavailable(
                        "Keeplane storage is unavailable"
                    ) from error

            setattr(cls, name, guarded)
    return cls


@contextmanager
def settings_change():
    # One row orders changes to classes, model approvals and optional Audit.
    # This preserves their cross-table invariants across app replicas.
    with transaction.atomic():
        Settings.objects.get_or_create(pk=1)
        settings = Settings.objects.select_for_update().get(pk=1)
        yield settings
