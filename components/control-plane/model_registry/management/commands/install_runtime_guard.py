"""Operator entry point for a fresh managed gateway; never a developer API."""

import os
from pathlib import Path

from common.api import MODEL_GATEWAY
from common.errors import StorageUnavailable
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from model_registry.installed_runtime import ModelPolicyUnavailable
from model_registry.runtime_installation import DjangoRuntimeInstallation


class Command(BaseCommand):
    help = "Enroll exact approved keyless/shared IDs on a fresh managed gateway"

    def add_arguments(self, parser):
        parser.add_argument("--model", action="append", required=True)
        parser.add_argument("--directory", default="/installed")
        parser.add_argument("--trusted-file", default="/installed/trusted.json")
        parser.add_argument("--callback-host", default="app:3000")

    def handle(self, *args, **options):
        directory = Path(options["directory"])
        if (
            str(directory) != "/installed"
            or settings.RUNTIME_GUARD_MANIFEST_FILE != str(directory / "manifest.json")
            or settings.RUNTIME_AUTHORIZER_KEY_FILE != str(directory / "callback-key")
        ):
            raise CommandError("Configure the private managed installation volume")
        try:
            DjangoRuntimeInstallation(
                MODEL_GATEWAY,
                directory,
                options["trusted_file"],
                os.environ.get("PROVIDER_KEY_DIR", ""),
                gateway_mode=os.environ.get("GATEWAY_MODE", "managed"),
                callback_host=options["callback_host"],
            ).install(options["model"])
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            StopIteration,
            ModelPolicyUnavailable,
            StorageUnavailable,
        ):
            raise CommandError(
                "Runtime enrollment did not complete. Access state could not be "
                "confirmed; stop the managed gateway and start a fresh instance "
                "before trying enrollment again."
            ) from None
        self.stdout.write("Protected runtime enrollment is ready.")
