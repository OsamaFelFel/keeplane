"""Order usage reports against Keeplane recording a model's provider (ADR 029).

When Keeplane records a model's provider it also records whether any hourly
total already holds that model name in the current UTC hour, for any
developer. If none does, the name is new this hour and usage priced from that
hour on is all this model's own; otherwise a reused name's earlier tokens may
share the hour, and pricing starts with the next hour.

The check has to see every report that landed before the origin was recorded,
including reports still being written by another app copy. Adding a report
takes a shared lock on the model name and the check takes it exclusively, so
the check waits for reports already being written, and a report that waits for
the check lands after the origin. SQLite gives the same order because
Keeplane opens every SQLite transaction as an immediate (writing) one.
"""

from datetime import timezone as dt_timezone

from django.db import connection

from .models import UsageTotal

# The first key of PostgreSQL's two-key advisory locks, kept for this use; the
# second is the model name's hash. A hash shared by two names only makes one
# wait briefly for the other.
LOCK_SPACE = 29


def _lock(model_id, shared):
    if connection.vendor != "postgresql":
        return
    function = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {function}(%s, hashtext(%s))", [LOCK_SPACE, model_id])


def adding_report(model_id):
    """Call inside the transaction that adds a report for ``model_id``."""
    _lock(model_id, shared=True)


def record_origin(model_id, now):
    """The moment a model's origin is recorded, and whether its hour is unused.

    Call inside the transaction that records the origin; ``now`` gives the
    current time. The hour is unused when no total holds ``model_id`` in it
    yet, for any developer. The lock is taken before the time is read and held
    until that transaction ends, so a report waiting for it lands after the
    origin is recorded. The check is a new statement after the lock, so under
    PostgreSQL's default isolation (read committed) it sees every report that
    finished first.
    """
    _lock(model_id, shared=False)
    recorded = now()
    hour = recorded.astimezone(dt_timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    return recorded, not UsageTotal.objects.filter(
        model_id=model_id, hour=hour
    ).exists()
