"""Register the fixed public browser client after optional Toolkit migrations."""

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Register the fixed Keeplane CLI browser sign-in client"

    def handle(self, *args, **options):
        if not apps.is_installed("oauth2_provider"):
            raise CommandError(
                "Install and migrate the CLI sign-in trial dependencies first"
            )
        from oauth2_provider.models import Application

        expected = {
            "client_type": Application.CLIENT_PUBLIC,
            "authorization_grant_type": Application.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "http://127.0.0.1/callback",
            "skip_authorization": False,
            "allowed_origins": "",
            "algorithm": "",
        }
        with transaction.atomic():
            application, _ = Application.objects.get_or_create(
                client_id="keeplane-cli", defaults={"name": "Keeplane CLI", **expected}
            )
            application = Application.objects.select_for_update().get(pk=application.pk)
            if any(
                getattr(application, key) != value for key, value in expected.items()
            ):
                raise CommandError(
                    "The existing CLI client differs; ask the installation operator to repair it"
                )
        self.stdout.write("Keeplane CLI browser client is registered.")
