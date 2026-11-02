"""Check Keeplane's installation credentials and list what they protect.

Used before and after a credential rotation (manage.py check_credentials). It
reports whether the database accepts the app's password, whether every gateway
copy accepts the mounted admin and runtime keys, and lists the registered
gateway models and Keeplane's model approvals so the two runs can be compared.
During a managed gateway key rotation the keys Secret may also hold the next
keys (admin-key-next, runtime-key-next) beside the current ones. Each copy's
answer to them is reported too, so an installer knows every copy accepts the
next keys before switching Keeplane to them.
It also reports the certificates Keeplane itself verifies (the database CA,
the database server's certificate, and with a customer-run HTTPS gateway its
CA and certificates) with their expiry dates; see
docs/guide/certificate-operations.md.
With the per-copy guard check on PostgreSQL (ADR 027), it also reports each
gateway copy's status role and confirmed guard; see
docs/guide/guard-status-roles.md.
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


def certificate_report(gateways, warning_days, now=None):
    """Certificates Keeplane verifies, and the sentences an operator must read.

    Returns (report, refusals, warnings). A refusal is an expired, not yet
    valid, unreadable or untrusted certificate; a warning is one that expires
    within warning_days.
    """
    import os
    from datetime import datetime, timezone

    from common import certificates
    from integrations.gateway.adapter import GATEWAY_CA_FILE, gateway_tls_context

    now = now or datetime.now(timezone.utc)
    report, refusals, warnings = {}, [], []

    def add(name, section, label):
        report[name] = section
        found, soon = certificates.problems(section, label)
        refusals.extend(found)
        warnings.extend(soon)

    settings = connection.settings_dict
    options = settings.get("OPTIONS") or {}
    if connection.vendor == "postgresql" and options.get("sslrootcert"):
        add("database_ca", certificates.ca_file(options["sslrootcert"], now, warning_days),
            "Database CA")
    if (connection.vendor == "postgresql" and options.get("sslrootcert")
            and str(options.get("sslmode", "")).startswith("verify")):
        context = None
        try:
            context = ssl_context_for_database(options)
        except (OSError, ValueError):
            add("database_server", {"address": settings.get("HOST"), "trusted": False,
                                    "problem": "the database CA file cannot be loaded"},
                "Database server")
        if context is not None:
            add("database_server", certificates.server_certificate(
                settings["HOST"], int(settings.get("PORT") or 5432), context, now,
                warning_days, postgres=True), "Database server")
    if os.environ.get(GATEWAY_CA_FILE):
        add("gateway_ca", certificates.ca_file(os.environ[GATEWAY_CA_FILE], now, warning_days),
            "Gateway CA")
    rows = []
    for gateway in gateways:
        address = certificates.https_address(gateway.base_url)
        if address is None:
            continue
        try:
            context = gateway_tls_context()
        except (OSError, ValueError):
            row = {"address": "%s:%s" % address, "trusted": False,
                   "problem": "the gateway CA file cannot be loaded"}
        else:
            row = certificates.server_certificate(*address, context, now, warning_days)
        found, soon = certificates.problems(row, "Gateway " + row["address"])
        refusals.extend(found)
        warnings.extend(soon)
        rows.append(row)
    if rows:
        report["gateway_servers"] = rows
    return report, refusals, warnings


def ssl_context_for_database(options):
    """The trust libpq applies: only the configured CA file; the name for verify-full."""
    import ssl

    context = ssl.create_default_context(cafile=options["sslrootcert"])
    context.check_hostname = options.get("sslmode") == "verify-full"
    return context


NOT_IN_USE = "not in use"
RERUN = "; run configure_guard_status_access again"


def guard_status_report(copies, now=None):
    """The guard-status roles and each copy's confirmed guard (ADR 027).

    Returns (report, problems, warnings). With the per-copy check off or
    without PostgreSQL the report is "not in use". Otherwise it checks, with
    the same catalog reads as configure_guard_status_access, that each listed
    copy's status role exists, can log in and is limited to its own row, and
    that the app role only reads the table; and it summarises each copy's row.
    Problems fail the check; a copy with no confirmed guard only warns. It
    never reads a status role's password: whether the enroller's mounted
    password works shows in the enroller's log.
    """
    from django.conf import settings

    if not getattr(settings, "GUARD_STATUS_CHECK", False) or connection.vendor != "postgresql":
        return NOT_IN_USE, [], []
    from django.utils import timezone

    try:
        with connection.cursor() as cursor:
            return _guard_status(cursor, copies, now or timezone.now())
    except DatabaseError:
        return (
            {"problem": "the guard-status table cannot be read"},
            ["Guard status: the guard-status table and roles cannot be read"],
            [],
        )
    finally:
        connection.close()


def _copy_names(copies):
    from urllib.parse import urlsplit

    from model_registry.guard_status import valid_copy_name

    names = []
    for copy in copies:
        try:
            names.append((urlsplit(copy.base_url).hostname or "").split(".", 1)[0])
        except (AttributeError, ValueError):
            return None
    if not names or not all(map(valid_copy_name, names)) or len(set(names)) != len(names):
        return None
    return names


def _role_problems(name, found, owner, read_only, label):
    """Sentences for one role's attributes; empty when it is an ordinary role."""
    problems = []
    if name == owner:
        problems.append(f"{label} {name} is the role that owns Keeplane's tables")
    if found["powerful"]:
        problems.append(
            f"{label} {name} is a superuser, can bypass row-level security or can "
            "create roles"
        )
    if found["in_owner"] and name != owner:
        problems.append(f"{label} {name} is a member of the migration role {owner}")
    if read_only is not None and name not in read_only:
        problems.append(f"{label} {name} doesn't have default_transaction_read_only = on")
    return problems


def _login_problems(name, found, label):
    problems = []
    if not found["can_login"]:
        problems.append(f"{label} {name} can't log in (NOLOGIN)")
    if found["password_expired"]:
        problems.append(f"{label} {name}'s password has expired (VALID UNTIL)")
    if not found["can_connect"]:
        problems.append(f"{label} {name} has no CONNECT on the database")
    return problems


def _guard_row(row, now):
    """One copy's row as the report shows it, with its guard status."""
    from model_registry.installed_runtime import valid_declaration
    from model_registry.policy import ModelPolicyUnavailable

    if row is None:
        return {"guard": "not recorded"}
    entry = {"updated_at": row.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ")}
    if not row.confirmed:
        return {"guard": "not confirmed", **entry}
    try:
        declaration = valid_declaration(row.declaration)
    except ModelPolicyUnavailable:
        return {"guard": "unreadable", **entry}
    return {
        "guard": "confirmed",
        "confirmed_at": row.confirmed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "age_minutes": max(0, int((now - row.confirmed_at).total_seconds() // 60)),
        "models": [
            {"id": model_id, "fingerprint": model["fingerprint"]}
            for model_id, model in sorted(declaration["models"].items())
        ],
        **entry,
    }


def _guard_status(cursor, copies, now):
    from model_registry import guard_status_access as access
    from model_registry.models import GatewayGuardStatus

    names = _copy_names(copies)
    if names is None:
        return (
            {"problem": "the gateway copy list doesn't name each copy"},
            ["Guard status: GATEWAY_COPY_URLS must list every gateway copy at its "
             "Pod address"],
            [],
        )
    app, _, owner = access.table_owner(cursor)
    if owner is None:
        return (
            {"problem": "the guard-status table doesn't exist"},
            ["Guard status: the guard-status table doesn't exist; run migrate"],
            [],
        )
    problems, warnings = [], []
    pairs = access.policy_pairs(access.policies(cursor), app)
    secured = access.row_security(cursor)
    report = {
        "row_security": "on" if secured else "off",
        "policies": "as set" if pairs is not None else "changed",
    }
    if not secured:
        problems.append("Guard status: row-level security is off for the guard-status "
                        "table" + RERUN)
    if pairs is None:
        problems.append("Guard status: the guard-status table's policies aren't the ones "
                        "configure_guard_status_access sets" + RERUN)
        pairs = {}
    roles = {name: pairs[name] for name in names if name in pairs}
    status_roles = list(roles.values())
    found = access.role_attributes(cursor, [app, *status_roles], owner)
    present = [role for role in status_roles if role in found]
    read_only = access.read_only_roles(cursor, present)
    # Only existing roles: pg_has_role fails on a role that doesn't exist.
    members = access.memberships(cursor, [app, *present])
    extra = access.extra_privileges(
        cursor,
        {app: None, **{role: access.STATUS_WRITES for role in present}},
    )
    lacking = access.missing_status_writes(cursor, present)

    def unsafe(role, label, read_only_roles):
        sentences = _role_problems(role, found[role], owner, read_only_roles, label)
        sentences += [f"{label} {role} belongs to {target}; revoke the membership"
                      for member, target in members if member == role]
        more = [f"{privilege} on {table}" for who, privilege, table in extra if who == role]
        if more:
            listed = ", ".join(more[:5]) + (f" and {len(more) - 5} more" if len(more) > 5 else "")
            sentences.append(f"{label} {role} has more access than allowed: {listed}")
        return sentences

    app_problems = unsafe(app, "The app role", None)
    report["app_role"] = "reads only" if not app_problems else "unsafe"
    problems.extend("Guard status: " + sentence for sentence in app_problems)

    rows = {row.copy_name: row
            for row in GatewayGuardStatus.objects.filter(copy_name__in=names)}
    report["copies"] = []
    for name in names:
        role = roles.get(name)
        label = f"Gateway copy {name}:"
        entry = {"copy": name, "status_role": role}
        if role is None:
            entry["role_status"] = "not paired"
            problems.append(f"{label} no status role is paired with it" + RERUN
                            + f" with --copy {name}=<role>")
        elif role not in found:
            entry["role_status"] = "missing"
            problems.append(f"{label} its status role {role} doesn't exist; ask your "
                            "database operator to create it")
        else:
            sentences = unsafe(role, "its status role", read_only)
            login = _login_problems(role, found[role], "its status role")
            needed = [privilege for who, privilege in lacking if who == role]
            write = (
                [f"its status role {role} can't record its row: it lacks "
                 + ", ".join(needed) + f" on {access.STATUS_TABLE}" + RERUN]
                if needed else []
            )
            entry["role_status"] = (
                "unsafe" if sentences
                else "cannot log in" if login
                else "cannot write" if write
                else "limited"
            )
            problems.extend(f"{label} {sentence}" for sentence in sentences + login + write)
        entry.update(_guard_row(rows.get(name), now))
        if entry["guard"] == "not recorded":
            problems.append(f"{label} its enroller has recorded no guard status yet")
        elif entry["guard"] == "unreadable":
            problems.append(f"{label} its confirmed guard status can't be read")
        elif entry["guard"] == "not confirmed":
            warnings.append(f"{label} no guard is confirmed; protected models are "
                            "refused through it until its enroller confirms one")
        report["copies"].append(entry)
    for name, role in sorted(pairs.items()):
        if name not in roles:
            problems.append(
                f"Gateway copy {name} is no longer listed but status role {role} is "
                "still paired with it; remove the role or its pairing"
            )
    return report, problems, warnings


def check(primary, copies, warning_days=None):
    """Return the report and whether every credential was accepted."""
    from common.certificates import WARNING_DAYS

    gateways = [primary, *(copy for copy in copies if copy.base_url != primary.base_url)]
    certificates, refusals, warnings = certificate_report(
        gateways, WARNING_DAYS if warning_days is None else warning_days)
    guard_status, guard_problems, guard_warnings = guard_status_report(copies)
    report = {
        "database": database_status(),
        "gateway": gateway_status(gateways),
        "gateway_models": gateway_models(primary),
        "approvals": approvals(),
        "certificates": certificates,
        "certificate_problems": refusals,
        "certificate_warnings": warnings,
        "guard_status": guard_status,
        "guard_status_problems": guard_problems,
        "guard_status_warnings": guard_warnings,
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
        and not refusals
        and not guard_problems
    )
    return report, passed
