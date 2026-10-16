"""One controlled native management attempt; no traffic admission or rollback."""

import re
from copy import deepcopy
from dataclasses import dataclass, field
from urllib.parse import quote

from common.storage import storage_service
from django.db import transaction
from model_registry.fingerprints import fingerprint
from model_registry.models import ModelApproval, ProviderKeyChoice

from .factory import NativeDefinitionCandidate, digest
from .models import DefinitionGeneration, DefinitionPublication


class PublicationUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class PublicationTarget:
    gateway: object = field(repr=False)
    expected_wiring: dict = field(repr=False)
    expected_effective: dict = field(repr=False)


@storage_service
class DjangoNativePublication:
    def __init__(self, factory, *, mode, targets, primary_target, controlled_model_ids):
        if (
            mode not in ("managed", "existing")
            or not isinstance(targets, dict)
            or not targets
        ):
            raise PublicationUnavailable("Declare the native publication targets")
        if mode == "managed" and len(targets) < 2:
            raise PublicationUnavailable(
                "Managed publication requires every serving target"
            )
        if (
            primary_target not in targets
            or not isinstance(controlled_model_ids, (set, frozenset))
            or not controlled_model_ids
        ):
            raise PublicationUnavailable(
                "Declare operator-controlled models and primary target"
            )
        self.targets = {}
        for name, target in targets.items():
            if (
                not isinstance(name, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name)
                or not isinstance(target, PublicationTarget)
            ):
                raise PublicationUnavailable("Declare a supported target")
            wiring = deepcopy(target.expected_wiring)
            effective = deepcopy(target.expected_effective)
            if (
                not isinstance(wiring, dict)
                or not {"config", "gateways", "binds", "policies"} <= wiring.keys()
                or not isinstance(effective, dict)
                or not {"config", "gateways", "binds", "policies"} <= effective.keys()
            ):
                raise PublicationUnavailable(
                    "Declare complete file and effective wiring"
                )
            self.targets[name] = PublicationTarget(target.gateway, wiring, effective)
        self.factory, self.mode, self.primary_target = factory, mode, primary_target
        # This trusted constructor declaration, never approval/client metadata,
        # determines which existing gateway resources the service may change.
        self.controlled = frozenset(controlled_model_ids)

    @staticmethod
    def _read(target, path):
        status, value = target.gateway.request(path, timeout=5, connection_retries=0)
        if status != 200 or not isinstance(value, dict):
            raise PublicationUnavailable("Native readback is unavailable")
        return value

    def _wiring(self, target):
        current = self._read(target, "/api/config")
        if digest(current) != digest(target.expected_wiring):
            raise PublicationUnavailable("Native wiring changed")
        return digest(current)

    def _resource(self, target, model_id):
        body = self._read(target, "/api/config/resources/llm.model")
        rows = body.get("resources")
        if not isinstance(rows, list):
            raise PublicationUnavailable("Native resource readback is incomplete")
        found = [
            row for row in rows if isinstance(row, dict) and row.get("id") == model_id
        ]
        if (
            len(found) != 1
            or type(found[0].get("revision")) is not int
            or not fingerprint(model_id, found)
        ):
            raise PublicationUnavailable("Native resource readback is incomplete")
        return found[0]

    @staticmethod
    def _expected_effective(current, candidate):
        expected = deepcopy(current)
        models = expected.get("llm", {}).get("models")
        if not isinstance(models, list):
            raise PublicationUnavailable("Native effective configuration is incomplete")
        matches = [
            i
            for i, row in enumerate(models)
            if isinstance(row, dict)
            and row.get("id", row.get("name")) == candidate.model_id
        ]
        if len(matches) != 1:
            raise PublicationUnavailable("Native effective model is ambiguous")
        models[matches[0]] = deepcopy(candidate.value)
        return digest(expected)

    @staticmethod
    def _persist(attempt, state, targets):
        with transaction.atomic(durable=True):
            attempt.state, attempt.targets = state, deepcopy(targets)
            attempt.failure = (
                "Publication could not be confirmed"
                if state in ("failed", "partial")
                else ""
            )
            attempt.save(update_fields=["state", "targets", "failure"])

    @staticmethod
    def _still_prepared(candidate):
        row = DefinitionGeneration.objects.filter(
            pk=candidate.generation,
            state="prepared",
            raw_fingerprint=candidate.raw_fingerprint,
            wiring_digest=candidate.wiring_digest,
            envelope_digest=candidate.envelope_digest,
        ).first()
        if (
            row is None
            or digest(candidate.value) != candidate.envelope_digest
            or row.envelope != candidate.value
            or not ModelApproval.objects.filter(
                pk=candidate.model_id,
                key_choice=ProviderKeyChoice.PERSONAL,
                gateway_fingerprint=candidate.raw_fingerprint,
            ).exists()
        ):
            raise PublicationUnavailable("The prepared candidate changed")

    def publish(self, candidate):
        if (
            transaction.get_connection().in_atomic_block
            or not transaction.get_autocommit()
        ):
            raise PublicationUnavailable(
                "Publication requires its own durable transaction"
            )
        if (
            not isinstance(candidate, NativeDefinitionCandidate)
            or candidate.model_id not in self.controlled
        ):
            raise PublicationUnavailable(
                "This model is not declared for operator control"
            )
        if (
            digest(self.targets[self.primary_target].expected_wiring)
            != candidate.wiring_digest
        ):
            raise PublicationUnavailable("Primary wiring does not match the candidate")
        observations = {
            name: {
                "state": "pending",
                "baseline_digest": digest(target.expected_effective),
            }
            for name, target in self.targets.items()
        }
        with transaction.atomic(durable=True):
            attempt = DefinitionPublication.objects.create(
                generation_id=candidate.generation,
                mode=self.mode,
                raw_fingerprint=candidate.raw_fingerprint,
                envelope_digest=candidate.envelope_digest,
                targets=observations,
            )
        wrote = False
        try:
            self.factory.require_current(candidate)
            initial, expected = {}, {}
            for name, target in self.targets.items():
                self._wiring(target)
                raw = self._resource(target, candidate.model_id)
                if fingerprint(candidate.model_id, [raw]) != candidate.raw_fingerprint:
                    raise PublicationUnavailable("Target raw definition changed")
                initial[name] = raw["revision"]
                effective = self._read(target, "/api/config/effective")
                if digest(effective) != digest(target.expected_effective):
                    raise PublicationUnavailable("Native effective baseline changed")
                expected[name] = self._expected_effective(
                    target.expected_effective, candidate
                )
            for name, target in self.targets.items():
                self._still_prepared(candidate)
                wiring = self._wiring(target)
                observations[name].update(state="submitted", wiring_digest=wiring)
                self._persist(attempt, "started", observations)
                wrote = True
                status, _ = target.gateway.request(
                    "/api/config/resources/llm.model/"
                    + quote(candidate.model_id, safe=""),
                    {"value": deepcopy(candidate.value)},
                    method="PUT",
                    timeout=5,
                    connection_retries=0,
                )
                if status != 200:
                    raise PublicationUnavailable("Native write was not confirmed")
            # Later writes may advance a shared store's revision. No earlier
            # readback is accepted as final; read EVERY target after ALL writes.
            for name, target in self.targets.items():
                self._still_prepared(candidate)
                wiring = self._wiring(target)
                row = self._resource(target, candidate.model_id)
                effective = digest(self._read(target, "/api/config/effective"))
                if (
                    row.get("value") != candidate.value
                    or row["revision"] <= initial[name]
                    or effective != expected[name]
                ):
                    raise PublicationUnavailable("Protected native readback changed")
                observations[name] = {
                    "state": "readback_complete",
                    "revision": row["revision"],
                    "protected_fingerprint": fingerprint(candidate.model_id, [row]),
                    "effective_digest": effective,
                    "wiring_digest": wiring,
                    "baseline_digest": digest(target.expected_effective),
                }
            self._still_prepared(candidate)
            self._persist(attempt, "readback_complete", observations)
        except Exception:  # noqa: BLE001 - retain unknown native writes without secret errors
            self._persist(attempt, "partial" if wrote else "failed", observations)
            raise PublicationUnavailable("Publication could not be confirmed") from None
        return {"state": attempt.state, "targets": deepcopy(observations)}
