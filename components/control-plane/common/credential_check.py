"""Check Keeplane's installation credentials and list what they protect.

Used before and after a credential rotation (manage.py check_credentials). It
reports whether the database accepts the app's password, whether every gateway
copy accepts the mounted admin and runtime keys, and lists the registered
gateway models and Keeplane's model approvals so the two runs can be compared.
During a managed gateway key rotation the keys Secret may also hold the next
keys (admin-key-next, runtime-key-next) beside the current ones. Each copy's
answer to them is reported too, so an installer knows every copy accepts the
next keys before switching Keeplane to them.
It only reads; it never prints a password, key, key hash or provider key.
"""

from pathlib import Path

from django.db import DatabaseError, connection
from model_registry.fingerprints import fingerprint

KEY_REFUSED = (
    "The gateway refused Keeplane's admin key. After a key change, restart the "
    "gateway copies so they load the new key hashes, or check gateway.keysSecret."
)
CHECKS = {"admin_key": "/api/runtime", "runtime_key": "/v1/models"}
# Report name -> (the key file it stands in for, the path that needs that key).
NEXT_CHECKS = {
    "admin_key_next": ("admin_key_file", "/api/runtime"),
    "runtime_key_next": ("runtime_key_file", "/v1/models"),
}


def key_status(status, body):
    if status == 200:
        return "accepted"
    if status in (401, 403):
        return "refused"
    if isinstance(body, dict) and body.get("error") == "Gateway credential unavailable":
        return "unreadable"
    return "unreachable"


PREVIOUS_PASSWORD = "connected with the previous password; the database refuses the mounted one"
# What a new process, such as `kubectl exec ... check_credentials`, sees between
# writing a new password to the Secret and changing the role: unlike the
# serving copies, it has no previous password in memory.
PASSWORD_REFUSED = "the database refuses the mounted password"
UNREACHABLE = "unreachable"


def database_status():
    from common.database_password import is_authentication_failure

    try:
        connection.ensure_connection()
    except DatabaseError as error:
        return PASSWORD_REFUSED if is_authentication_failure(error) else UNREACHABLE
    finally:
        connection.close()
    path = connection.settings_dict.get("PASSWORD_FILE")
    if path:
        from common.postgresql.base import rotating_password

        if rotating_password(path).previous_in_use:
            return PREVIOUS_PASSWORD
    return "connected"


def next_key_file(current):
    """The next key mounted beside a current key file, or "" when none is."""
    if not current:
        return ""
    candidate = Path(current).with_name(Path(current).name + "-next")
    return str(candidate) if candidate.is_file() else ""


def next_key_status(gateway, attribute, path):
    """A copy's answer to the next key, or None when no next key is mounted."""
    from integrations.gateway.adapter import AgentgatewayModelAdapter

    files = {
        "runtime_key_file": getattr(gateway, "runtime_key_file", ""),
        "admin_key_file": getattr(gateway, "admin_key_file", ""),
    }
    files[attribute] = next_key_file(files[attribute])
    if not files[attribute]:
        return None
    candidate = AgentgatewayModelAdapter(gateway.base_url, **files)
    return key_status(*candidate.request(path, timeout=10))


def gateway_status(gateways):
    rows = []
    for gateway in gateways:
        row = {
            "address": gateway.base_url,
            **{
                name: key_status(*gateway.request(path, timeout=10))
                for name, path in CHECKS.items()
            },
        }
        for name, (attribute, path) in NEXT_CHECKS.items():
            status = next_key_status(gateway, attribute, path)
            if status is not None:
                row[name] = status
        rows.append(row)
    return rows


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
            row[name] == "accepted"
            for row in report["gateway"]
            for name in (*CHECKS, *NEXT_CHECKS)
            if name in row
        )
        and report["gateway_models"] is not None
        and report["approvals"] is not None
    )
    return report, passed
