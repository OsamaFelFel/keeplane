"""Restrict the guard-status table and the enroller's roles (ADR 027).

Run with the migration credential, which owns Keeplane's tables, after
``migrate`` and after your database operator has created the login roles (see
docs/guide/guard-status-roles.md). Role creation needs a privilege Keeplane's
roles never get, and passwords stay with the operator, so this command only
grants, revokes and sets row-level security on tables Keeplane owns. It is
idempotent: run it again whenever the gateway copies change, and every role
it does not list loses its access to the table.

Afterwards:

- the enroller approvals role can only read model approvals;
- each copy's status role can read, insert and update only its own copy's row
  of the guard-status table, and nothing else;
- the app role can only read the guard-status table.

The command checks the result and refuses, changing nothing, if any role
still has more.
"""

import re

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections, transaction
from integrations.gateway.runtime_config import COPY_NAME

from model_registry.models import GatewayGuardStatus, ModelApproval

ROLE = re.compile(r"[a-z_][a-z0-9_]{0,62}")
STATUS_TABLE = GatewayGuardStatus._meta.db_table
APPROVAL_TABLE = ModelApproval._meta.db_table
TABLE_PRIVILEGES = (
    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"
)
STATUS_WRITES = {(STATUS_TABLE, privilege) for privilege in ("SELECT", "INSERT", "UPDATE")}


def copy_role(value):
    copy_name, separator, role = value.partition("=")
    if not separator or not COPY_NAME.fullmatch(copy_name) or not ROLE.fullmatch(role):
        raise ValueError()
    return copy_name, role


class Command(BaseCommand):
    help = "Restrict the guard-status table and the model enroller's database roles"

    def add_arguments(self, parser):
        parser.add_argument("--app-role", required=True)
        parser.add_argument("--enroller-role", required=True)
        parser.add_argument(
            "--copy",
            action="append",
            required=True,
            metavar="POD=ROLE",
            help="A gateway copy's Pod name and its status role; once per copy",
        )
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        app, enroller = options["app_role"], options["enroller_role"]
        try:
            copies = [copy_role(value) for value in options["copy"]]
        except ValueError:
            raise CommandError(
                "Name each copy as POD=ROLE: a Pod name, then a lowercase role name"
            ) from None
        status_roles = [role for _, role in copies]
        names = [copy_name for copy_name, _ in copies]
        roles = [app, enroller, *status_roles]
        if (
            not all(ROLE.fullmatch(role) for role in (app, enroller))
            or len(set(roles)) != len(roles)
            or len(set(names)) != len(names)
        ):
            raise CommandError(
                "Use a different lowercase role for the app, the enroller and each copy"
            )
        connection = connections[options["database"]]
        if connection.vendor != "postgresql":
            raise CommandError("Guard status access applies to PostgreSQL only")
        try:
            with transaction.atomic(using=options["database"]):
                with connection.cursor() as cursor:
                    self._configure(cursor, connection, app, enroller, copies)
        except DatabaseError as error:
            raise CommandError(
                "Guard status access was not changed: " + type(error).__name__
            ) from None
        self.stdout.write(
            f"Guard status access is set for {len(copies)} gateway "
            f"{'copy' if len(copies) == 1 else 'copies'}: the app reads, each copy "
            "writes only its own row, and the enroller reads only approvals."
        )

    def _configure(self, cursor, connection, app, enroller, copies):
        quote = connection.ops.quote_name
        status_roles = [role for _, role in copies]
        cursor.execute(
            "SELECT current_user, current_schema(), "
            "(SELECT tableowner FROM pg_tables "
            " WHERE schemaname = current_schema() AND tablename = %s)",
            [STATUS_TABLE],
        )
        owner, schema, table_owner = cursor.fetchone()
        if table_owner is None:
            raise CommandError("Run migrate before setting guard status access")
        if table_owner != owner:
            raise CommandError("Run this with the migration credential that owns the tables")
        roles = [app, enroller, *status_roles]
        cursor.execute(
            "SELECT rolname, rolsuper OR rolbypassrls OR rolcreaterole, "
            "pg_has_role(rolname, %s, 'MEMBER') "
            "FROM pg_roles WHERE rolname = ANY(%s)",
            [owner, roles],
        )
        found = {name: (powerful, member) for name, powerful, member in cursor.fetchall()}
        missing = [role for role in roles if role not in found]
        if missing:
            raise CommandError(
                "Ask your database operator to create these roles first: "
                + ", ".join(missing)
            )
        if owner in roles or any(powerful or member for powerful, member in found.values()):
            raise CommandError(
                "The app, enroller and status roles must be separate ordinary roles: "
                "not the owner, superusers, row-security bypassers, role creators "
                "or members of the migration role"
            )
        cursor.execute(
            "SELECT r.rolname FROM pg_roles r WHERE r.rolname = ANY(%s) AND EXISTS ("
            " SELECT 1 FROM pg_db_role_setting s"
            " WHERE s.setrole = r.oid"
            " AND s.setdatabase IN (0, (SELECT oid FROM pg_database"
            "   WHERE datname = current_database()))"
            " AND 'default_transaction_read_only=on' = ANY(s.setconfig))",
            [[enroller, *status_roles]],
        )
        read_only = {row[0] for row in cursor.fetchall()}
        unset = [role for role in (enroller, *status_roles) if role not in read_only]
        if unset:
            raise CommandError(
                "Set default_transaction_read_only = on for these roles first: "
                + ", ".join(unset)
            )

        table, approvals = quote(STATUS_TABLE), quote(APPROVAL_TABLE)
        schema_name = quote(schema)
        restricted = ", ".join(quote(role) for role in (enroller, *status_roles))
        # Nothing on any Keeplane table for the enroller or status roles...
        cursor.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {schema_name} FROM {restricted}")
        cursor.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema_name} FROM {restricted}")
        # ...and nobody but the owner on the status table, until granted below.
        cursor.execute(
            "SELECT DISTINCT acl.grantee FROM pg_class c, aclexplode(c.relacl) acl "
            "WHERE c.oid = %s::regclass",
            [f"{schema}.{STATUS_TABLE}"],
        )
        grantees = [row[0] for row in cursor.fetchall()]
        cursor.execute(f"REVOKE ALL ON {table} FROM PUBLIC")
        cursor.execute(
            "SELECT rolname FROM pg_roles WHERE oid = ANY(%s) AND rolname <> %s",
            [grantees, owner],
        )
        for (grantee,) in cursor.fetchall():
            cursor.execute(f"REVOKE ALL ON {table} FROM {quote(grantee)}")
        cursor.execute(f"GRANT SELECT ON {table} TO {quote(app)}")
        cursor.execute(
            f"GRANT SELECT, INSERT, UPDATE ON {table} TO "
            + ", ".join(quote(role) for role in status_roles)
        )
        cursor.execute(f"GRANT SELECT ON {approvals} TO {quote(enroller)}")

        # Row-level security: the app reads every row; each status role reads
        # and writes only its own copy's row. The pairs are written into the
        # policy itself, so no role needs any other table to be checked.
        cursor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        cursor.execute(
            "SELECT policyname FROM pg_policies "
            "WHERE schemaname = current_schema() AND tablename = %s",
            [STATUS_TABLE],
        )
        for (policy,) in cursor.fetchall():
            cursor.execute(f"DROP POLICY {quote(policy)} ON {table}")
        cursor.execute(
            f"CREATE POLICY guard_status_app_read ON {table} "
            f"FOR SELECT TO {quote(app)} USING (true)"
        )
        pairs = ", ".join(f"('{copy_name}', '{role}')" for copy_name, role in copies)
        own_row = f"(copy_name, current_user::text) IN (VALUES {pairs})"
        cursor.execute(
            f"CREATE POLICY guard_status_own_copy ON {table} FOR ALL TO "
            + ", ".join(quote(role) for role in status_roles)
            + f" USING ({own_row}) WITH CHECK ({own_row})"
        )
        self._verify(cursor, app, enroller, status_roles)

    @staticmethod
    def _verify(cursor, app, enroller, status_roles):
        """Every privilege each role holds, from any source, is the intended one."""
        allowed = {
            app: None,  # only the status table is checked for the app
            enroller: {(APPROVAL_TABLE, "SELECT")},
            **{role: STATUS_WRITES for role in status_roles},
        }
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
                        extra.append(f"{role} {privilege} on {name}")
                elif (name, privilege) not in permitted:
                    extra.append(f"{role} {privilege} on {name}")
        if extra:
            raise CommandError(
                "These roles still have more access than allowed (check grants "
                "to PUBLIC and role memberships): " + "; ".join(sorted(extra)[:20])
            )
