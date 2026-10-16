"""Fresh operator enrollment for the fixed, managed runtime trial."""

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

from common.storage import storage_service
from integrations.gateway.applied import (
    AppliedStateUnavailable,
    applied_fingerprint,
    read_applied,
)

from .authorization import ModelAccessDenied
from .fingerprints import fingerprint
from .models import ModelApproval
from .policy import ModelPolicyUnavailable, registry_rows
from .provider_keys import managed_key_digest

HEX = re.compile(r"[a-f0-9]{64}")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")


def digest(value):
    try:
        return hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
    except (ValueError, TypeError, RecursionError):
        raise ModelPolicyUnavailable("Runtime configuration is malformed") from None


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate enrollment field")
        result[key] = value
    return result


def manifest(path):
    """The configured file is operator authority, never a client enrollment."""
    try:
        if not Path(path).is_absolute():
            raise ValueError()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid not in (0, os.geteuid())
                or metadata.st_mode & 0o022
            ):
                raise ValueError()
            raw = source.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        value = json.loads(raw, object_pairs_hook=unique_pairs)
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "version",
                "enabled",
                "file_digest",
                "effective_digest",
                "applied_digest",
                "models",
            }
            or type(value["version"]) is not int
            or value["version"] != 2
            or value["enabled"] is not True
            or any(
                not isinstance(value[key], str) or not HEX.fullmatch(value[key])
                for key in ("file_digest", "effective_digest", "applied_digest")
            )
            or not isinstance(value["models"], dict)
            or not 1 <= len(value["models"]) <= 32
        ):
            raise ValueError()
        for model_id, row in value["models"].items():
            if (
                not MODEL_ID.fullmatch(model_id)
                or not isinstance(row, dict)
                or set(row) != {"fingerprint", "key_choice", "key_name", "key_digest"}
                or not isinstance(row["fingerprint"], str)
                or not HEX.fullmatch(row["fingerprint"])
                or row["key_choice"] not in ("none", "shared", "personal")
                or (
                    row["key_choice"] in ("none", "personal")
                    and (row["key_name"] != "" or row["key_digest"] != "")
                )
                or (
                    row["key_choice"] == "shared"
                    and (
                        not isinstance(row["key_name"], str)
                        or not re.fullmatch(r"key-[a-f0-9]{32}", row["key_name"])
                        or not isinstance(row["key_digest"], str)
                        or not HEX.fullmatch(row["key_digest"])
                    )
                )
            ):
                raise ValueError()
        return value
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ModelPolicyUnavailable("Runtime enrollment is unavailable") from None


@storage_service
class DjangoInstalledRuntimeGate:
    def __init__(self, gateway, manifest_file, key_directory):
        self.gateway, self.manifest_file, self.key_directory = (
            gateway,
            manifest_file,
            key_directory,
        )

    def _read(self, path):
        try:
            status, body = self.gateway.request(path, timeout=5, connection_retries=0)
        except (OSError, ValueError, RecursionError):
            raise ModelPolicyUnavailable(
                "Runtime configuration is unavailable"
            ) from None
        if status != 200 or not isinstance(body, dict):
            raise ModelPolicyUnavailable("Runtime configuration is unavailable")
        if (
            path in ("/api/config", "/api/config/effective")
            and not {"config", "gateways", "binds", "policies"} <= body.keys()
        ):
            raise ModelPolicyUnavailable("Complete runtime wiring is unavailable")
        return body

    def require_installed(self, model_id, selected_fingerprint=None):
        declaration = manifest(self.manifest_file)
        expected = declaration["models"].get(model_id)
        if expected is None:
            raise ModelAccessDenied(
                403, "This model is not installed for runtime access"
            )
        self.require_definition(model_id, expected, selected_fingerprint)
        for path, key in (
            ("/api/config", "file_digest"),
            ("/api/config/effective", "effective_digest"),
        ):
            if digest(self._read(path)) != declaration[key]:
                raise ModelPolicyUnavailable("Installed runtime wiring changed")
        try:
            if (
                applied_fingerprint(read_applied(self.gateway))
                != declaration["applied_digest"]
            ):
                raise AppliedStateUnavailable()
        except AppliedStateUnavailable:
            raise ModelPolicyUnavailable("Applied runtime wiring changed") from None
        return expected

    def require_definition(self, model_id, expected, selected_fingerprint=None):
        """Installer preflight only; this alone never authorizes inference."""
        resources = registry_rows(
            self._read("/api/config/resources/llm.model"), "resources"
        )
        row = next((row for row in resources if row["id"] == model_id), None)
        if row is None or type(row.get("revision")) is not int:
            raise ModelPolicyUnavailable("Installed model revision is unavailable")
        current = fingerprint(model_id, resources)
        approval = ModelApproval.objects.filter(pk=model_id).first()
        if (
            current != expected["fingerprint"]
            or (selected_fingerprint is not None and selected_fingerprint != current)
            or approval is None
            or approval.gateway_fingerprint != current
            or approval.key_choice != expected["key_choice"]
        ):
            raise ModelPolicyUnavailable("Installed model definition changed")
        value = row.get("value")
        params = value.get("params") if isinstance(value, dict) else None
        if (
            not isinstance(params, dict)
            or set(params) - {"model", "baseUrl"}
            or not isinstance(params.get("model"), str)
            or not 0 < len(params["model"]) <= 256
            or set(value) - {"id", "name", "provider", "params", "auth"}
            or value.get("id") != model_id
            or value.get("name") != model_id
            or value.get("provider")
            not in (
                "openAI",
                "anthropic",
                {"custom": {"formats": [{"type": "completions"}]}},
            )
        ):
            raise ModelPolicyUnavailable("Installed model format is unsupported")
        try:
            base = params.get("baseUrl", "https://provider.invalid")
            if (
                not isinstance(base, str)
                or not 0 < len(base) <= 2048
                or any(ord(char) < 33 or ord(char) > 126 for char in base)
            ):
                raise ValueError()
            url = urlsplit(base)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
            ):
                raise ValueError()
            _ = url.port
        except (ValueError, TypeError):
            raise ModelPolicyUnavailable(
                "Installed provider address is unsupported"
            ) from None
        if expected["key_choice"] == "personal" and (
            value["provider"] not in ("openAI", "anthropic") or url.scheme != "https"
        ):
            raise ModelPolicyUnavailable("Installed personal provider is unsupported")
        if expected["key_choice"] in ("none", "personal"):
            auth = value.get("auth")
            if auth is not None and (not isinstance(auth, dict) or auth):
                raise ModelPolicyUnavailable("Installed key choice changed")
        else:
            path = str(Path(self.key_directory) / expected["key_name"])
            if (
                value.get("auth") != {"key": {"value": {"file": path}}}
                or managed_key_digest(self.key_directory, path)
                != expected["key_digest"]
            ):
                raise ModelPolicyUnavailable("Installed shared key changed")
