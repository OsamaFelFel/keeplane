"""Check Keeplane's installation credentials and list what they protect.

Used before and after a credential rotation (manage.py check_credentials). It
reports whether the database accepts the app's password, whether every gateway
copy accepts the mounted admin and runtime keys, and lists the registered
gateway models and Keeplane's model approvals so the two runs can be compared.
It only reads; it never prints a password, key, key hash or provider key.
"""

from django.db import DatabaseError, connection
from model_registry.fingerprints import fingerprint

KEY_REFUSED = (
    "The gateway refused Keeplane's admin key. After a key change, restart the "
    "gateway copies so they load the new key hashes, or check gateway.keysSecret."
)
CHECKS = {"admin_key": "/api/runtime", "runtime_key": "/v1/models"}


def key_status(status, body):
    if status == 200:
        return "accepted"
    if status in (401, 403):
        return "refused"
    if isinstance(body, dict) and body.get("error") == "Gateway credential unavailable":
        return "unreadable"
    return "unreachable"


PREVIOUS_PASSWORD = "connected with the previous password; the database refuses the mounted one"


def database_status():
    try:
        connection.ensure_connection()
    except DatabaseError:
        return "refused or unreachable"
    finally:
        connection.close()
    path = connection.settings_dict.get("PASSWORD_FILE")
    if path:
        from common.postgresql.base import rotating_password

        if rotating_password(path).previous_in_use:
            return PREVIOUS_PASSWORD
    return "connected"


def gateway_status(gateways):
    return [
        {
            "address": gateway.base_url,
            **{
                name: key_status(*gateway.request(path, timeout=10))
                for name, path in CHECKS.items()
            },
        }
        for gateway in gateways
    ]


def gateway_models(gateway):
    status, body = gateway.resources()
    rows = body.get("resources") if status == 200 and isinstance(body, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return None
    return sorted(
        ({"id": row.get("id"), "fingerprint": fingerprint(row.get("id"), rows)}
         for row in rows),
        key=lambda row: str(row["id"]),
    )


def approvals():
    from model_registry.models import ModelApproval

    try:
        rows = list(ModelApproval.objects.order_by("model_id"))
    except DatabaseError:
        return None
    finally:
        connection.close()
    return [
        {
            "id": row.model_id,
            "key_choice": row.key_choice,
            "approved_classes": sorted(row.approved_classes),
            "gateway_fingerprint": row.gateway_fingerprint,
            "set_up_by_keeplane": row.owned_by_keeplane,
        }
        for row in rows
    ]


def check(primary, copies):
    """Return the report and whether every credential was accepted."""
    gateways = [primary, *(copy for copy in copies if copy.base_url != primary.base_url)]
    report = {
        "database": database_status(),
        "gateway": gateway_status(gateways),
        "gateway_models": gateway_models(primary),
        "approvals": approvals(),
    }
    passed = (
        report["database"] == "connected"
        and all(
            row[name] == "accepted" for row in report["gateway"] for name in CHECKS
        )
        and report["gateway_models"] is not None
        and report["approvals"] is not None
    )
    return report, passed
