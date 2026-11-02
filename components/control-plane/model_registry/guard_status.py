"""Each managed gateway copy's confirmed guard, for the app to check (ADR 027).

In Kubernetes the guard lives in a Pod-local volume the app never mounts. Each
copy's model enroller therefore records the declaration it confirmed by
readback in the guard-status table, one row per copy, named by the copy's
StatefulSet Pod name. Its write uses a separate connection and role whose only
grant is on this table, and whose row-level security policy admits only its
own copy's row (``manage.py configure_guard_status_access``).

When the per-copy check is on (``KEEPLANE_GUARD_STATUS_CHECK=1``), the app
admits a protected check only when the copy that sent it has a confirmed row
listing the model with the same definition fingerprint. It then checks every
digest and the applied state on that same copy, through its private address in
``GATEWAY_COPY_URLS``. A missing, unconfirmed or malformed row, an unknown copy
or an unreadable copy refuses the call. The Docker preview keeps no row and
reads the private declaration file instead.
"""

import json
import logging
from urllib.parse import urlsplit

from common.storage import storage_service
from django.conf import settings
from django.db import DatabaseError, connections, transaction
from django.utils import timezone
from integrations.gateway.runtime_config import COPY_NAME

from .installed_runtime import DjangoInstalledRuntimeGate, valid_declaration
from .models import GatewayGuardStatus
from .policy import ModelPolicyUnavailable

STATUS_DATABASE = "guard_status"
TABLE = GatewayGuardStatus._meta.db_table

log = logging.getLogger(__name__)


def per_copy_check():
    """Whether the app checks each sending copy's guard-status row."""
    return bool(getattr(settings, "GUARD_STATUS_CHECK", False))


def valid_copy_name(value):
    return isinstance(value, str) and COPY_NAME.fullmatch(value) is not None


def copy_declaration(copy_name):
    """A reader for one copy's confirmed declaration; refuses anything else."""

    def read():
        try:
            row = (
                GatewayGuardStatus.objects.filter(pk=copy_name)
                .values("confirmed", "declaration")
                .first()
            )
        except DatabaseError:
            raise ModelPolicyUnavailable("Gateway guard status is unavailable") from None
        if row is None or row["confirmed"] is not True:
            raise ModelPolicyUnavailable("This gateway copy has no confirmed guard")
        return valid_declaration(row["declaration"])

    return read


def copy_gateway(copy_name, copies):
    """The one listed copy whose private address names this Pod."""
    if getattr(copies, "misconfigured", False) or not valid_copy_name(copy_name):
        raise ModelPolicyUnavailable("This gateway copy is not known")
    matches = []
    for copy in copies.copies:
        try:
            host = urlsplit(copy.base_url).hostname or ""
        except (AttributeError, ValueError):
            continue
        if host.split(".", 1)[0] == copy_name:
            matches.append(copy)
    if len(matches) != 1:
        raise ModelPolicyUnavailable("This gateway copy is not known")
    return matches[0]


def installed_gate(body, gateway, manifest_file, key_directory, copies):
    """The installed-runtime gate for a protected check from a managed copy.

    With the per-copy check off this is the private declaration file and the
    gateway address, as before. With it on, the check must name its copy, and
    both the declaration and every gateway read come from that copy.
    """
    if not per_copy_check():
        return DjangoInstalledRuntimeGate(gateway, manifest_file, key_directory)
    copy_name = body.get("gateway_copy")
    return DjangoInstalledRuntimeGate(
        copy_gateway(copy_name, copies),
        None,
        key_directory,
        declaration=copy_declaration(copy_name),
    )


def confirmed_everywhere(model_id, fingerprint, key_choice, copies):
    """The model's declaration row when every listed copy confirmed it alike.

    Returns None unless every listed copy's confirmed row lists this exact
    model with the same fingerprint, key choice and shared key. Used only to
    pick a model before a request is sent; the copy that serves the request is
    checked again, in full, at its own checks.
    """
    if getattr(copies, "misconfigured", False) or not copies.copies:
        return None
    names = []
    for copy in copies.copies:
        try:
            names.append((urlsplit(copy.base_url).hostname or "").split(".", 1)[0])
        except (AttributeError, ValueError):
            return None
    if not all(valid_copy_name(name) for name in names) or len(set(names)) != len(
        names
    ):
        return None
    try:
        rows = {
            row["copy_name"]: row
            for row in GatewayGuardStatus.objects.filter(
                copy_name__in=names, confirmed=True
            ).values("copy_name", "declaration")
        }
    except DatabaseError:
        return None
    entries = []
    for name in names:
        try:
            declaration = valid_declaration(rows[name]["declaration"])
        except (KeyError, ModelPolicyUnavailable):
            return None
        entries.append(declaration["models"].get(model_id))
    first = entries[0]
    if (
        first is None
        or any(entry != first for entry in entries)
        or first["fingerprint"] != fingerprint
        or first["key_choice"] != key_choice
    ):
        return None
    return dict(first)


@storage_service
class GuardStatusRecorder:
    """The enroller's only database write: its own copy's guard-status row.

    It uses its own connection (``DATABASES["guard_status"]``), whose role has
    every transaction read-only by default. A write opens an explicit
    ``BEGIN READ WRITE`` transaction, which overrides that for this one
    transaction only. The approval connection stays read-only throughout.
    """

    def __init__(self, copy_name, *, using=STATUS_DATABASE, clock=timezone.now):
        if not valid_copy_name(copy_name):
            raise ValueError("The gateway copy name is not valid")
        self.copy_name, self.using, self.clock = copy_name, using, clock

    def current(self):
        """This copy's row as (confirmed, declaration), or None when absent."""
        row = (
            GatewayGuardStatus.objects.using(self.using)
            .filter(pk=self.copy_name)
            .values("confirmed", "declaration")
            .first()
        )
        return None if row is None else (row["confirmed"], row["declaration"])

    def confirm(self, declaration):
        """Record the declaration this copy just confirmed by readback."""
        valid_declaration(declaration)
        if self.current() != (True, declaration):
            self._write(True, declaration)

    def clear(self):
        """Record that nothing is confirmed on this copy."""
        if self.current() != (False, None):
            self._write(False, None)

    def _write(self, confirmed, declaration):
        now = self.clock()
        values = {
            "confirmed": confirmed,
            "declaration": declaration,
            "confirmed_at": now if confirmed else None,
            "updated_at": now,
        }
        connection = connections[self.using]
        if connection.vendor != "postgresql":
            # Test databases only: the per-copy mode refuses to start without
            # PostgreSQL (see run_model_enroller).
            with transaction.atomic(using=self.using):
                GatewayGuardStatus.objects.using(self.using).update_or_create(
                    copy_name=self.copy_name, defaults=values
                )
            return
        if connection.in_atomic_block:
            raise DatabaseError("The guard status write needs its own transaction")
        with connection.cursor() as cursor:
            cursor.execute("BEGIN READ WRITE")
            try:
                cursor.execute(
                    f"INSERT INTO {TABLE} "
                    "(copy_name, confirmed, declaration, confirmed_at, updated_at) "
                    "VALUES (%s, %s, %s::jsonb, %s, %s) "
                    "ON CONFLICT (copy_name) DO UPDATE SET "
                    "confirmed = EXCLUDED.confirmed, "
                    "declaration = EXCLUDED.declaration, "
                    "confirmed_at = EXCLUDED.confirmed_at, "
                    "updated_at = EXCLUDED.updated_at",
                    [
                        self.copy_name,
                        confirmed,
                        None if declaration is None else json.dumps(declaration),
                        values["confirmed_at"],
                        now,
                    ],
                )
                cursor.execute("COMMIT")
            except BaseException:
                try:
                    cursor.execute("ROLLBACK")
                except DatabaseError:
                    pass
                raise
