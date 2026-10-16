"""Retry file deletions already authorized by committed account removals."""

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from model_registry.key_cleanup import cleanup_pending


class Command(BaseCommand):
    help = "Retry pending provider-key file deletions; print counts only."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        try:
            result = cleanup_pending(limit=options["limit"])
        except (DatabaseError, ValueError):
            raise CommandError(
                "Provider-key cleanup is unavailable; check the database and limit"
            ) from None
        self.stdout.write(
            f"Completed {result['removed']} key file deletions; {result['pending']} pending."
        )
        if result["pending"]:
            raise CommandError(
                "Provider-key deletions remain pending; check storage and retry"
            )
