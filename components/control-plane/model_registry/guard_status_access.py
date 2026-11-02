"""Read what the guard-status roles may do in PostgreSQL (ADR 027).

Shared by ``manage.py configure_guard_status_access``, which sets the grants
and refuses any role that could do more, and ``manage.py check_credentials``,
which reports the same checks without changing anything. Every query here only
reads the system catalogs, which any role can read, so the app role can run
them too. Nothing here reads or prints a password.
"""

import re

from model_registry.models import GatewayGuardStatus, ModelApproval

ROLE = re.compile(r"[a-z_][a-z0-9_]{0,62}")
STATUS_TABLE = GatewayGuardStatus._meta.db_table
APPROVAL_TABLE = ModelApproval._meta.db_table
TABLE_PRIVILEGES = (
    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"
)
STATUS_WRITES = {(STATUS_TABLE, privilege) for privilege in ("SELECT", "INSERT", "UPDATE")}
APP_READ_POLICY = "guard_status_app_read"
OWN_COPY_POLICY = "guard_status_own_copy"
# One (copy, role) pair as PostgreSQL prints the own-copy policy's condition,
# for example ('keeplane-gateway-0'::text,'keeplane_status_0'::text).
POLICY_PAIR = re.compile(r"\('([a-z0-9-]+)'::text,\s*'([a-z_][a-z0-9_]*)'::text\)")


def own_row_condition(copies):
    """The own-copy policy's condition for (copy name, role) pairs.

    The names are checked by the caller (Pod names and lowercase role names),
    so they can be written into the policy as literals.
    """
    pairs = ", ".join(f"('{copy_name}', '{role}')" for copy_name, role in copies)
    return f"(copy_name, current_user::text) IN (VALUES {pairs})"


def table_owner(cursor):
    """(current user, current schema, owner of the status table or None)."""
    cursor.execute(
        "SELECT current_user, current_schema(), "
        "(SELECT tableowner FROM pg_tables "
        " WHERE schemaname = current_schema() AND tablename = %s)",
        [STATUS_TABLE],
    )
    return cursor.fetchone()


def role_attributes(cursor, roles, owner):
    """Each existing role's attributes; a missing role is left out.

    ``powerful`` is a superuser, row-security bypasser or role creator;
    ``in_owner`` is a member of the role that owns Keeplane's tables.
    """
    cursor.execute(
        "SELECT rolname, rolsuper OR rolbypassrls OR rolcreaterole, "
        "pg_has_role(rolname, %s, 'MEMBER'), rolcanlogin, "
        "rolvaliduntil IS NOT NULL AND rolvaliduntil <= now(), "
        "has_database_privilege(rolname, current_database(), 'CONNECT') "
        "FROM pg_roles WHERE rolname = ANY(%s)",
        [owner, list(roles)],
    )
    return {
        name: {
            "powerful": powerful,
            "in_owner": member,
            "can_login": can_login,
            "password_expired": expired,
            "can_connect": connect,
        }
        for name, powerful, member, can_login, expired, connect in cursor.fetchall()
    }


def read_only_roles(cursor, roles):
    """The roles whose transactions are read-only by default in this database."""
    cursor.execute(
        "SELECT r.rolname FROM pg_roles r WHERE r.rolname = ANY(%s) AND EXISTS ("
        " SELECT 1 FROM pg_db_role_setting s"
        " WHERE s.setrole = r.oid"
        " AND s.setdatabase IN (0, (SELECT oid FROM pg_database"
        "   WHERE datname = current_database()))"
        " AND 'default_transaction_read_only=on' = ANY(s.setconfig))",
        [list(roles)],
    )
    return {row[0] for row in cursor.fetchall()}


def memberships(cursor, listed):
    """(member, target) pairs among the listed roles, with or without INHERIT.

    A member can SET ROLE to the other role and act as it, for example as
    another copy's status role.
    """
    listed = list(listed)
    cursor.execute(
        "SELECT member.name, target.name "
        "FROM unnest(%s::text[]) AS member(name), unnest(%s::text[]) AS target(name) "
        "WHERE member.name <> target.name "
        "AND pg_has_role(member.name, target.name, 'MEMBER')",
        [listed, listed],
    )
    return sorted(cursor.fetchall())


def extra_privileges(cursor, allowed):
    """(role, privilege, relation) for every privilege beyond the allowed ones.

    ``allowed`` maps a role to the (relation, privilege) pairs it may hold in
    Keeplane's schema, from any source (its own grants, PUBLIC or a role it
    belongs to). ``None`` checks only the status table, where only SELECT is
    allowed (the app role).
    """
    extra = []
    for role, permitted in allowed.items():
        cursor.execute(
            "SELECT c.relname, p.privilege FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "CROSS JOIN unnest(%s::text[]) AS p(privilege) "
            "WHERE n.nspname = current_schema() "
            "AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
            "AND has_table_privilege(%s, c.oid, p.privilege) "
            "UNION ALL "
            "SELECT c.relname, p.privilege FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "CROSS JOIN unnest(ARRAY['SELECT', 'UPDATE', 'USAGE']) AS p(privilege) "
            "WHERE n.nspname = current_schema() AND c.relkind = 'S' "
            "AND has_sequence_privilege(%s, c.oid, p.privilege)",
            [list(TABLE_PRIVILEGES), role, role],
        )
        for name, privilege in cursor.fetchall():
            if permitted is None:
                if name == STATUS_TABLE and privilege != "SELECT":
                    extra.append((role, privilege, name))
            elif (name, privilege) not in permitted:
                extra.append((role, privilege, name))
    return sorted(extra)


def row_security(cursor):
    """Whether row-level security is on for the status table, or None if absent."""
    cursor.execute(
        "SELECT c.relrowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relname = %s",
        [STATUS_TABLE],
    )
    row = cursor.fetchone()
    return None if row is None else row[0]


def policies(cursor):
    """The status table's policies as {name: (command, roles, using, check)}."""
    cursor.execute(
        "SELECT policyname, cmd, roles::text[], coalesce(qual, ''), "
        "coalesce(with_check, '') FROM pg_policies "
        "WHERE schemaname = current_schema() AND tablename = %s",
        [STATUS_TABLE],
    )
    return {
        name: (command, set(roles), using, check)
        for name, command, roles, using, check in cursor.fetchall()
    }


# What is left of a printed own-copy condition once its pairs are removed
# (spaces dropped); the column is varchar, so it is printed with a cast.
POLICY_REST = re.compile(
    r"\(\((?:\(copy_name\)::text|copy_name),\(CURRENT_USER\)::text\)IN\(VALUES(,*)\)\)"
)


def _only_pairs(condition, count):
    """Whether a printed own-copy condition holds nothing but its pairs."""
    rest = POLICY_REST.fullmatch(re.sub(r"\s+", "", POLICY_PAIR.sub("", condition)))
    return rest is not None and len(rest.group(1)) == count - 1


def policy_pairs(found, app):
    """The own-copy policy's {copy name: role}, or None when it isn't as set.

    The table must have exactly the two policies
    ``configure_guard_status_access`` writes: the app's read policy, for the
    app role only, and the own-copy policy, whose condition is nothing but the
    (copy, role) pairs, the same for reading and writing, applying only to the
    roles it pairs, each copy and each role once.
    """
    if set(found) != {APP_READ_POLICY, OWN_COPY_POLICY}:
        return None
    command, roles, using, check = found[APP_READ_POLICY]
    if command != "SELECT" or roles != {app} or using.strip("() ") != "true" or check:
        return None
    command, roles, using, check = found[OWN_COPY_POLICY]
    pairs = POLICY_PAIR.findall(using)
    if (
        command != "ALL"
        or not pairs
        or sorted(pairs) != sorted(POLICY_PAIR.findall(check))
        or not _only_pairs(using, len(pairs))
        or not _only_pairs(check, len(pairs))
        or len({name for name, _ in pairs}) != len(pairs)
        or len({role for _, role in pairs}) != len(pairs)
        or roles != {role for _, role in pairs}
    ):
        return None
    return dict(pairs)
