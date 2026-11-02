"""Check the database password and gateway keys this app copy is using.

Prints one JSON report and exits 1 when any credential is refused, a list
cannot be read, or a certificate Keeplane verifies is expired, not yet valid,
unreadable or untrusted. A certificate that expires within
--certificate-warning-days (default 30) is listed under certificate_warnings
without failing the check. With KEEPLANE_GUARD_STATUS_CHECK=1 on PostgreSQL
it also exits 1 when a gateway copy's status role is missing, can't log in or
could do more than configure_guard_status_access allows, or when a copy has
recorded no guard status (docs/guide/guard-status-roles.md). Run it before and after a rotation and compare the
gateway_models and approvals lists; see docs/guide/postgres-accounts.md and
docs/guide/gateway-configuration.md and docs/guide/certificate-operations.md.
"""

import json

from django.core.management.base import BaseCommand

from common.credential_check import check


class Command(BaseCommand):
    help = "Check installation credentials and list registered models and approvals"

    def add_arguments(self, parser):
        parser.add_argument(
            "--certificate-warning-days", type=int, default=30, metavar="DAYS",
            help="List certificates that expire within this many days (default 30)",
        )

    def handle(self, *args, **options):
        from common.api import MODEL_GATEWAY, MODEL_GATEWAY_COPIES

        days = options["certificate_warning_days"]
        if days < 0:
            raise SystemExit("--certificate-warning-days must be 0 or more")
        report, passed = check(MODEL_GATEWAY, MODEL_GATEWAY_COPIES.copies, days)
        report["passed"] = passed
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if not passed:
            raise SystemExit(1)
