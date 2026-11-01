"""Check a restored Keeplane database before letting people back in.

Prints one JSON report and exits 1 when migrations are pending or unknown, or
a registered developer key file is missing or unreadable. Run it after a
restore, and compare its counts with the run you saved when taking the backup;
see docs/guide/backup-and-restore.md. It only reads and never prints a
password, session key, provider key or key filename.
"""

import json

from django.core.management.base import BaseCommand
from django.db import DatabaseError

from common.restore_check import check

UNREADABLE = (
    "Keeplane can't read the database. Check that this app copy points at the "
    "restored database and that it accepts the app's password (run "
    "check_credentials)."
)


class Command(BaseCommand):
    help = "Report migration state and record counts of a restored database"

    def handle(self, *args, **options):
        try:
            report, passed = check()
        except DatabaseError:
            report = {"problems": [UNREADABLE]}
            passed = False
        report["passed"] = passed
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if not passed:
            raise SystemExit(1)
