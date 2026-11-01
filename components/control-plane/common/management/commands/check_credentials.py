"""Check the database password and gateway keys this app copy is using.

Prints one JSON report and exits 1 when any credential is refused or a list
cannot be read. Run it before and after a rotation and compare the
gateway_models and approvals lists; see docs/guide/postgres-accounts.md and
docs/guide/gateway-configuration.md.
"""

import json

from django.core.management.base import BaseCommand

from common.credential_check import check


class Command(BaseCommand):
    help = "Check installation credentials and list registered models and approvals"

    def handle(self, *args, **options):
        from common.api import MODEL_GATEWAY, MODEL_GATEWAY_COPIES

        report, passed = check(MODEL_GATEWAY, MODEL_GATEWAY_COPIES.copies)
        report["passed"] = passed
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if not passed:
            raise SystemExit(1)
