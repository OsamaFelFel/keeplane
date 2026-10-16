"""Prepare key-free native definitions; publication and dispatch stay disconnected."""

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass, field

from common.storage import settings_change, storage_service
from django.db import transaction

from .models import DefinitionGeneration

HEADER = "x-keeplane-definition-generation"
REMOVE_HEADERS = [
    HEADER,
    "x-keeplane-project-id",
    "x-keeplane-gateway-credential",
    "x-keeplane-actor-id",
    "x-keeplane-workload-id",
    "x-api-key",
    "x-provider-authorization",
]


class GenerationUnavailable(ValueError):
    pass


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class NativeDefinitionCandidate:
    generation: uuid.UUID
    model_id: str
    raw_fingerprint: str
    wiring_digest: str
    envelope_digest: str
    value: dict = field(repr=False)


def envelope(definition, generation):
    value = deepcopy(definition.value)
    value["authorization"] = {
        "rules": [
            {
                "require": (
                    '(request.method == "GET" && request.path == "/v1/models") || '
                    f'request.headers["{HEADER}"] == "{generation.hex}"'
                )
            }
        ]
    }
    # Authorization must be overwritten by the final trusted key callback.
    # Removing it here would also remove that server-selected provider key.
    value["requestHeaders"] = {"remove": list(REMOVE_HEADERS)}
    return value


@storage_service
class DjangoNativeDefinitionFactory:
    def __init__(self, validator, *, expected_wiring, read_wiring):
        if not callable(read_wiring) or not callable(
            getattr(validator, "raw_definition", None)
        ):
            raise GenerationUnavailable(
                "Configure fresh server definition and wiring readers"
            )
        self.validator, self.read_wiring = validator, read_wiring
        self.expected_wiring_digest = self._complete_wiring_digest(expected_wiring)

    @staticmethod
    def _complete_wiring_digest(value):
        # Bind the whole supplied configuration, including unknown/global fields.
        # The native acceptance gate must separately prove its enforcement.
        if (
            not isinstance(value, dict)
            or not {"config", "gateways", "binds", "policies"} <= value.keys()
        ):
            raise GenerationUnavailable(
                "Provide the complete native wiring configuration"
            )
        return digest(value)

    def _wiring_digest(self):
        current = self._complete_wiring_digest(self.read_wiring())
        if current != self.expected_wiring_digest:
            raise GenerationUnavailable("Native authorization wiring changed")
        return current

    @staticmethod
    def _durable_boundary():
        if (
            transaction.get_connection().in_atomic_block
            or not transaction.get_autocommit()
        ):
            raise GenerationUnavailable(
                "Generation changes require their own durable transaction"
            )

    @staticmethod
    def _candidate(row):
        return NativeDefinitionCandidate(
            row.generation,
            row.model_id,
            row.raw_fingerprint,
            row.wiring_digest,
            row.envelope_digest,
            deepcopy(row.envelope),
        )

    def prepare(self, model_id):
        self._durable_boundary()
        if not isinstance(model_id, str) or not 0 < len(model_id) <= 256:
            raise GenerationUnavailable("Choose a model")
        raw = self.validator.raw_definition(model_id)
        wiring = self._wiring_digest()
        # Commit the reservation before constructing or returning any envelope.
        with transaction.atomic(durable=True), settings_change():
            row = DefinitionGeneration.objects.create(
                generation=uuid.uuid4(),
                model_id=model_id,
                raw_fingerprint=raw.definition_fingerprint,
                wiring_digest=wiring,
            )
        try:
            value = envelope(raw, row.generation)
            with transaction.atomic(durable=True), settings_change():
                reserved = DefinitionGeneration.objects.select_for_update().get(
                    pk=row.pk
                )
                current = self.validator.raw_definition(model_id, lock=True)
                if (
                    reserved.state != "reserved"
                    or current != raw
                    or self._wiring_digest() != wiring
                ):
                    raise GenerationUnavailable("Definition preparation became stale")
                DefinitionGeneration.objects.filter(
                    model_id=model_id, state="prepared"
                ).update(state="retired")
                row.envelope, row.envelope_digest, row.state = (
                    value,
                    digest(value),
                    "prepared",
                )
                row.save(update_fields=["envelope", "envelope_digest", "state"])
        except BaseException:
            # A crash can leave a reserved tombstone; it never becomes current.
            with transaction.atomic(durable=True):
                DefinitionGeneration.objects.filter(pk=row.pk, state="reserved").update(
                    state="failed"
                )
            raise
        return self._candidate(row)

    def require_current(self, candidate):
        if not isinstance(candidate, NativeDefinitionCandidate):
            raise GenerationUnavailable("Choose a prepared definition")
        row = DefinitionGeneration.objects.filter(
            pk=candidate.generation, state="prepared"
        ).first()
        if row is None or self._candidate(row) != candidate:
            raise GenerationUnavailable("This generation is no longer prepared")
        current = self.validator.raw_definition(row.model_id)
        if (
            current.definition_fingerprint != row.raw_fingerprint
            or self._wiring_digest() != row.wiring_digest
            or digest(row.envelope) != row.envelope_digest
            or digest(envelope(current, row.generation)) != row.envelope_digest
        ):
            raise GenerationUnavailable("Prepared definition changed")
        return candidate

    def retire(self, model_id):
        """Call before controlled removal; retain every previous reservation."""
        self._durable_boundary()
        with transaction.atomic(durable=True), settings_change():
            DefinitionGeneration.objects.filter(
                model_id=model_id, state__in=("reserved", "prepared")
            ).update(state="retired")

    def reject(self, generation):
        """Retain a candidate that failed a later, separate native acceptance."""
        self._durable_boundary()
        with transaction.atomic(durable=True), settings_change():
            DefinitionGeneration.objects.filter(
                pk=generation, state__in=("reserved", "prepared")
            ).update(state="failed")
