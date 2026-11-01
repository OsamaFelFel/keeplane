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

from model_registry.guard_status import (
    STATUS_DATABASE,
    GuardStatusRecorder,
    valid_copy_name,
)
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
POSTGRESQL = ("common.postgresql", "django.db.backends.postgresql")


def guard_status_recorder(databases=None):
    """This copy's name and guard-status recorder in Kubernetes; else (None, None).

    ADR 027: in Kubernetes the enroller names its copy (``KEEPLANE_GATEWAY_COPY``,
    the StatefulSet Pod name) and records that copy's confirmed guard on a
    separate PostgreSQL connection (``KEEPLANE_GUARD_STATUS_DATABASE_USER`` and
    ``..._PASSWORD_FILE``). Approval reads stay on the read-only connection
    (``KEEPLANE_DATABASE_READ_ONLY=1``). The Docker preview sets none of these.
    """
    databases = settings.DATABASES if databases is None else databases
    copy_name = os.environ.get("KEEPLANE_GATEWAY_COPY", "")
    configured = STATUS_DATABASE in databases
    if not copy_name and not configured:
        return None, None
    if not copy_name or not configured:
        raise CommandError(
            "Set both the gateway copy name and the guard status database, or neither"
        )
    if not valid_copy_name(copy_name):
        raise CommandError("The gateway copy name is not a valid Pod name")
    default, status = databases["default"], databases[STATUS_DATABASE]
    if (
        default["ENGINE"] not in POSTGRESQL
        or status["ENGINE"] not in POSTGRESQL
        or "default_transaction_read_only=on"
        not in default.get("OPTIONS", {}).get("options", "")
        or default.get("USER") == status.get("USER")
    ):
        raise CommandError(
            "Guard status needs PostgreSQL, a read-only approvals connection and "
            "a separate status role"
        )
    return copy_name, GuardStatusRecorder(copy_name)


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
        copy_name, status = guard_status_recorder()
        enroller = DjangoModelEnroller(
            DjangoRuntimeInstallation(
                MODEL_GATEWAY,
                directory,
                options["trusted_file"],
                os.environ.get("PROVIDER_KEY_DIR", ""),
                gateway_mode=os.environ.get("GATEWAY_MODE", "managed"),
                callback_host=options["callback_host"],
                gateway_copy=copy_name,
            ),
            status=status,
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
