"""Operator entry point for a fresh managed gateway; never a developer API."""

import os
from pathlib import Path

from common.api import MODEL_GATEWAY
from common.errors import StorageUnavailable
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from model_registry.guard_status import valid_copy_name
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
        # Kubernetes (ADR 027): name this copy in its protected checks. The
        # copy's enroller records its guard status on its first pass.
        copy_name = os.environ.get("KEEPLANE_GATEWAY_COPY") or None
        if copy_name is not None and not valid_copy_name(copy_name):
            raise CommandError("The gateway copy name is not a valid Pod name")
        try:
            DjangoRuntimeInstallation(
                MODEL_GATEWAY,
                directory,
                options["trusted_file"],
                os.environ.get("PROVIDER_KEY_DIR", ""),
                gateway_mode=os.environ.get("GATEWAY_MODE", "managed"),
                callback_host=options["callback_host"],
                gateway_copy=copy_name,
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
