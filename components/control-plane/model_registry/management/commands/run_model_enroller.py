"""The private model enroller for a managed gateway copy (ADR 027).

It runs beside one gateway copy, in that copy's network namespace, and is the
only process that writes the copy's private guard directory. It has no
listener, takes no request from the app and reads approvals only.
"""

import logging
import os
import time
from pathlib import Path

from common.api import MODEL_GATEWAY
from common.errors import StorageUnavailable
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from model_registry.installed_runtime import ModelPolicyUnavailable
from model_registry.model_enroller import DjangoModelEnroller
from model_registry.runtime_installation import DjangoRuntimeInstallation

FAILURES = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    StopIteration,
    ModelPolicyUnavailable,
    StorageUnavailable,
)
FAILED = (
    "Model enrolment did not complete. Protected model access stays refused "
    "until the next attempt succeeds."
)

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Keep the managed gateway's protected checks in step with saved models"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=2.0)
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
        if not 1.0 <= options["interval"] <= 60.0:
            raise CommandError("Choose an interval from 1 to 60 seconds")
        enroller = DjangoModelEnroller(
            DjangoRuntimeInstallation(
                MODEL_GATEWAY,
                directory,
                options["trusted_file"],
                os.environ.get("PROVIDER_KEY_DIR", ""),
                gateway_mode=os.environ.get("GATEWAY_MODE", "managed"),
                callback_host=options["callback_host"],
            )
        )
        if options["once"]:
            try:
                result = enroller.reconcile()
            except FAILURES:
                raise CommandError(FAILED) from None
            self.stdout.write(self._summary(result))
            return
        last = None
        while True:
            try:
                result = enroller.reconcile()
            except FAILURES:
                log.warning(FAILED)
                last = None
            else:
                if result != last and not (
                    last is not None
                    and result.state == "unchanged"
                    and result.models == last.models
                ):
                    self.stdout.write(self._summary(result))
                    self.stdout.flush()
                last = result
            time.sleep(options["interval"])

    @staticmethod
    def _summary(result):
        count = len(result.models)
        if result.state == "held":
            return (
                "A model change is waiting for requests already under way to "
                "finish. Changed or removed models stay refused until then."
            )
        if result.state == "withdrawn" or not count:
            return "No model is enrolled for protected access."
        noun = "model is" if count == 1 else "models are"
        if result.state == "unchanged":
            return f"Protected access is up to date: {count} {noun} enrolled."
        return f"Protected access is ready: {count} {noun} enrolled."
