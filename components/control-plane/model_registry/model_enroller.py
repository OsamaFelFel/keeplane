"""Re-enrol the managed gateway's protected checks from confirmed approvals.

ADR 027. The enroller is a private process, separate from the web-facing app.
It reads model approvals only (the app saves an add or a widening only after
every gateway copy confirms it, so a saved approval is a confirmed one), works
out which models the protected runtime may serve, and replaces the guard on a
running gateway copy without a restart:

1. Nothing changes when the enabled declaration already matches the plan and
   still verifies against the gateway (idempotent).
2. Otherwise the declaration is disabled first, so every protected call is
   refused while the guard is replaced. Nothing is ever served from a guard
   that has not been read back.
3. The new guard is written, read back from the applied gateway state, and only
   then is the declaration enabled again for exactly the planned models.

A withdrawal needs no enroller: the app refuses a removed or narrowed model as
soon as the change is saved. The enroller then drops its guard.

The guard binds every model's final check to that model's definition
fingerprint. A request already in flight under an older guard carries the older
fingerprint, which no longer matches the saved approval, so it is refused.

The pinned gateway reads routing and a model's backend policy at different
stages, and a request keeps its backend snapshot through its retries. If a
model's guard were replaced or removed while such a request is in flight, its
next final check could pair the old destination with the new guard, or find no
guard at all. So when the plan would change or remove the guard of a model that
is being served, the enroller first waits until every request routed before the
change has passed its last final check (HOLD_SECONDS). Meanwhile the old guard
and declaration stay as they are: the app refuses the changed or removed model,
and every model if the gateway's own state moved. Adding a model changes no
existing guard and is enrolled at once.

In Kubernetes the app cannot read the copy's private declaration, so the
enroller also records it in the copy's guard-status row (see guard_status):
before the guard moves the row says nothing is confirmed, and only after the
new guard reads back does it list the enrolled models again. A pass that fails
after that point leaves nothing confirmed; one that fails before touching the
guard keeps the last confirmation. The Docker preview keeps no row.
"""

import json
import logging
import time
from dataclasses import dataclass

from common.storage import storage_service
from integrations.gateway.runtime_config import (
    ATTEMPT_TIMEOUT,
    RETRY_ATTEMPTS,
    RETRY_BACKOFF,
    RuntimeInstallationUnavailable,
    callback_copies,
)

from .fingerprints import fingerprint
from .installed_runtime import (
    MODEL_ID,
    DjangoInstalledRuntimeGate,
    ModelPolicyUnavailable,
    digest,
    manifest,
)
from .models import ModelApproval
from .runtime_installation import (
    DjangoRuntimeInstallation,
    atomic_private,
    private_lock,
    trusted_base,
)

MAX_MODELS = 32
DISABLED = {"version": 2, "enabled": False}
PROTECTED_BIND = "bind/5000"
RECORD = "served.json"
# The longest a request can keep an old backend snapshot before its last final
# check: each native attempt may wait for the provider's headers, plus the
# backoffs between attempts and a margin for the entry check.
if ATTEMPT_TIMEOUT != "60s" or RETRY_BACKOFF != "500ms":
    raise ImportError("Recalculate the enroller's hold for the new retry policy")
HOLD_SECONDS = (RETRY_ATTEMPTS + 1) * 60 + RETRY_ATTEMPTS * 0.5 + 15

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Enrolment:
    # "unchanged", "enrolled", "withdrawn" (no model is enrolled) or "held"
    # (a change waits for requests under the old guard, which is left as is).
    state: str
    models: tuple


@storage_service
class DjangoModelEnroller:
    """The only writer of one gateway copy's private guard directory."""

    def __init__(
        self,
        installation,
        *,
        deadline=15.0,
        sleep=time.sleep,
        now=time.monotonic,
        status=None,
    ):
        if not isinstance(installation, DjangoRuntimeInstallation):
            raise TypeError("A managed runtime installation is required")
        if (status is None) != (installation.gateway_copy is None) or (
            status is not None and status.copy_name != installation.gateway_copy
        ):
            raise TypeError("Record guard status for exactly this gateway copy")
        self.installation = installation
        self.deadline, self.sleep, self.now = deadline, sleep, now
        # Kubernetes only: this copy's guard-status recorder (ADR 027).
        self.status = status

    @property
    def directory(self):
        return self.installation.directory

    def _read(self, path):
        return self.installation._read(path)

    def plan(self, resources, file_models):
        """The guard declaration rows for every model that may be enrolled now.

        A model is left out (and so refused) when its approval no longer matches
        the gateway's definition, its definition is unsupported, or its shared
        key is unavailable. Leaving one model out never blocks the others.
        """
        planned = {}
        gate = DjangoInstalledRuntimeGate(
            self.installation.gateway,
            str(self.directory / "manifest.json"),
            self.installation.key_directory,
        )
        for approval in ModelApproval.objects.order_by("model_id"):
            identifier = approval.model_id
            if (
                not MODEL_ID.fullmatch(identifier)
                or identifier in file_models
                or approval.gateway_fingerprint != fingerprint(identifier, resources)
            ):
                continue
            try:
                row = self.installation._models([identifier], resources)[identifier]
                gate.require_definition(identifier, row)
            except (
                RuntimeInstallationUnavailable,
                ModelPolicyUnavailable,
                KeyError,
                TypeError,
                ValueError,
            ):
                log.warning("A saved model was left out of the protected runtime")
                continue
            planned[identifier] = row
        if len(planned) > MAX_MODELS:
            raise RuntimeInstallationUnavailable(
                "More models are approved than the protected runtime can enrol"
            )
        return planned

    def _current(self, planned):
        """The enabled declaration when it is exactly the plan and still holds."""
        active = self.directory / "manifest.json"
        try:
            declaration = manifest(active)
        except ModelPolicyUnavailable:
            return None
        if declaration["models"] != planned:
            return None
        # Every protected check must name exactly this copy (none in Docker).
        try:
            config = json.loads((self.directory / "gateway.json").read_bytes())
        except (OSError, ValueError, RecursionError):
            return None
        if callback_copies(config) != {self.installation.gateway_copy}:
            return None
        gate = DjangoInstalledRuntimeGate(
            self.installation.gateway, str(active), self.installation.key_directory
        )
        try:
            for identifier in planned:
                gate.require_installed(identifier)
        except ModelPolicyUnavailable:
            return None
        return declaration

    def _withdrawn(self, base):
        """With nothing to enrol, serve only the trusted base: no protected port."""
        config_file = self.directory / "gateway.json"
        try:
            if json.loads(config_file.read_bytes()) == base and digest(
                self._read("/api/config")
            ) == digest(base):
                applied = self.installation.read_applied()
                if not any(
                    bind.get("key") == PROTECTED_BIND for bind in applied["binds"]
                ):
                    return False
        except (OSError, ValueError, KeyError, TypeError):
            pass
        atomic_private(config_file, base)
        end = time.monotonic() + self.deadline
        while True:
            try:
                applied = self.installation.read_applied()
                if not any(
                    bind.get("key") == PROTECTED_BIND for bind in applied["binds"]
                ) and digest(self._read("/api/config")) == digest(base):
                    return True
            except (RuntimeInstallationUnavailable, KeyError, TypeError):
                pass
            if time.monotonic() >= end:
                raise RuntimeInstallationUnavailable(
                    "The gateway has not dropped the protected runtime"
                )
            self.sleep(0.1)

    def reconcile(self):
        # Set once this pass starts to disable or change the guard.
        self._moving = False
        try:
            return self._reconcile()
        except Exception:
            # ADR 027 "Failure": a pass that failed before touching the guard
            # keeps the copy's last confirmation; one that disabled or changed
            # it leaves nothing confirmed (the row was cleared first; this
            # repeats that in case a later write moved it on).
            if self._moving:
                self._unconfirmed()
            raise

    def _unconfirmed(self):
        if self.status is None:
            return
        try:
            self.status.clear()
        except Exception:  # noqa: BLE001 - the pass already failed; keep its error
            log.warning("This gateway copy's guard status could not be cleared")

    def _confirmed(self, declaration):
        if self.status is not None:
            self.status.confirm(declaration)

    def _reconcile(self):
        installation = self.installation
        if (
            installation.gateway_mode != "managed"
            or installation.gateway.base_url != "http://127.0.0.1:4000"
        ):
            raise RuntimeInstallationUnavailable("Use the managed gateway enroller")
        with private_lock(self.directory, installation.trusted_file):
            base, _ = trusted_base(installation.trusted_file)
            resources = self._read("/api/config/resources")["resources"]
            if not isinstance(resources, list) or any(
                not isinstance(row, dict) or row.get("kind") != "llm.model"
                for row in resources
            ):
                raise RuntimeInstallationUnavailable(
                    "This fixed installation supports model resources only"
                )
            file_models = {row["name"] for row in base.get("llm", {}).get("models", [])}
            planned = self.plan(resources, file_models)
            wanted = {key: row["fingerprint"] for key, row in planned.items()}
            record = self._record()
            current = self._current(planned) if planned else None
            if current is not None:
                self._save(record, {"served": wanted, "pending": None})
                # Read back just now; record it if the row says otherwise
                # (a first pass after the operator's enrolment or a restart).
                self._confirmed(current)
                return Enrolment("unchanged", tuple(planned))
            active = self.directory / "manifest.json"
            try:
                previous = manifest(active)
            except ModelPolicyUnavailable:
                previous = None
            served = self._served(record, previous)
            if served is None or any(
                wanted.get(key) != value for key, value in served.items()
            ):
                # A served model's guard would change or go: wait out requests
                # that may still hold its old backend.
                pending = record.get("pending") if record else None
                key = digest(wanted)
                now = self.now()
                # A start in the future means the monotonic clock restarted
                # (a reboot); start the hold again rather than trust it.
                if (
                    pending is None
                    or pending.get("plan") != key
                    or pending["since"] > now
                ):
                    value = {
                        "served": served or {},
                        "pending": {"plan": key, "since": now},
                    }
                    if served is None:
                        value["unknown"] = True
                    self._save(record, value)
                    return Enrolment("held", ())
                if now - pending["since"] < HOLD_SECONDS:
                    return Enrolment("held", ())
            # Refuse every protected call before the guard moves. In
            # Kubernetes the app reads the row, so it goes first: if it cannot
            # be written, the guard is not touched.
            self._moving = True
            if self.status is not None:
                self.status.clear()
            atomic_private(active, DISABLED)
            if not planned:
                changed = self._withdrawn(base)
                self._save(record, {"served": {}, "pending": None})
                state = "withdrawn" if changed or previous else "unchanged"
                return Enrolment(state, ())
            initial = installation.read_applied()
            result = installation.publish(base, resources, planned, initial)
            self._save(record, {"served": wanted, "pending": None})
            # Only now, with the new guard read back and enabled.
            self._confirmed(manifest(active))
            return Enrolment("enrolled", tuple(result["models"]))

    def _record(self):
        """What the enabled guard last served, and any change being held."""
        path = self.directory / RECORD
        try:
            value = json.loads(path.read_bytes())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, RecursionError):
            return None
        pending = value.get("pending") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("served"), dict)
            or any(not isinstance(row, str) for row in value["served"].values())
            or (
                pending is not None
                and (
                    not isinstance(pending, dict)
                    or not isinstance(pending.get("plan"), str)
                    or type(pending.get("since")) not in (int, float)
                )
            )
        ):
            return None
        return value

    @staticmethod
    def _served(record, previous):
        """Models with a guard in place; None when that cannot be known."""
        if record is None or record.get("unknown"):
            return None
        if "served" in record:
            return dict(record["served"])
        if previous is not None:
            return {key: row["fingerprint"] for key, row in previous["models"].items()}
        return {}

    def _save(self, record, value):
        current = (
            {"served": record.get("served"), "pending": record.get("pending")}
            if record
            else None
        )
        if record and record.get("unknown"):
            current["unknown"] = True
        if current != value:
            atomic_private(self.directory / RECORD, value)
