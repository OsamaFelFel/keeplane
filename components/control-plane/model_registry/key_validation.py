"""Validate one submitted key against a current server-approved definition."""

import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from django.db import transaction

from .fingerprints import fingerprint
from .models import ModelApproval, ProviderKeyChoice
from .policy import registry_rows


class ProviderKeyRefused(Exception):
    pass


@dataclass(frozen=True)
class VerifiedProviderKey:
    owner_id: str
    model_id: str
    definition_fingerprint: str


@dataclass(frozen=True)
class RawProviderDefinition:
    model_id: str
    definition_fingerprint: str
    revision: int
    value: dict = field(repr=False)


class DjangoProviderKeyValidator:
    def __init__(self, gateway, *, timeout=8, allow_loopback_http=False):
        if not 0 < timeout <= 10:
            raise ValueError("Choose a validation deadline up to ten seconds")
        if type(allow_loopback_http) is not bool:
            raise ValueError("Choose whether to allow loopback HTTP")
        self.gateway, self.timeout = gateway, timeout
        self.allow_loopback_http = allow_loopback_http

    def _parsed_definition(self, model_id, lock=False):
        approvals = (
            ModelApproval.objects.select_for_update() if lock else ModelApproval.objects
        )
        approval = approvals.filter(
            pk=model_id, key_choice=ProviderKeyChoice.PERSONAL
        ).first()
        if approval is None:
            raise ValueError("This model does not accept developer keys")
        # Management reads retain the adapter's socket timeout, not a wall deadline.
        # Never send a submitted provider key to the management endpoint.
        status, body = self.gateway.request(
            "/api/config/resources/llm.model", timeout=5, connection_retries=0
        )
        if status != 200:
            raise ValueError("Current model definition is unavailable")
        resources = registry_rows(body, "resources")
        current = fingerprint(model_id, resources)
        if not current or current != approval.gateway_fingerprint:
            raise ValueError("Current model definition changed")
        value = next(row.get("value") for row in resources if row["id"] == model_id)
        if not isinstance(value, dict):
            raise ValueError("This provider definition is unsupported")
        params, provider = value.get("params"), value.get("provider")
        if (
            not isinstance(params, dict)
            or set(params) - {"model", "baseUrl"}
            or not isinstance(params.get("model"), str)
            or not 0 < len(params["model"]) <= 256
            or set(value) - {"name", "provider", "params", "auth"}
            or value.get("auth")
            or provider not in ("openAI", "anthropic")
        ):
            raise ValueError("This provider definition is unsupported")
        base = params.get(
            "baseUrl",
            {
                "openAI": "https://api.openai.com/v1",
                "anthropic": "https://api.anthropic.com/v1",
            }[provider],
        )
        if (
            not isinstance(base, str)
            or not 0 < len(base) <= 2048
            or any(ord(c) < 33 or ord(c) > 126 for c in base)
        ):
            raise ValueError("This provider address is unsupported")
        url = urlsplit(base)
        loopback = (
            self.allow_loopback_http
            and url.scheme == "http"
            and url.hostname in ("localhost", "127.0.0.1", "::1")
        )
        if (
            (url.scheme != "https" and not loopback)
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
        ):
            raise ValueError("Use an approved HTTPS provider address")
        _ = url.port  # Reject malformed ports before secret contact.
        suffix = "/chat/completions" if provider == "openAI" else "/messages"
        entry = next(row for row in resources if row["id"] == model_id)
        return RawProviderDefinition(
            model_id, current, entry["revision"], deepcopy(value)
        ), {
            "provider": provider,
            "model": params["model"],
            "url": base.rstrip("/") + suffix,
        }

    def raw_definition(self, model_id, *, lock=False):
        """Read a strict approved definition without sending a key or provider call."""
        if lock and not transaction.get_connection().in_atomic_block:
            raise RuntimeError("Lock the raw definition inside a transaction")
        return self._parsed_definition(model_id, lock)[0]

    def _definition(self, model_id, lock=False):
        definition, request = self._parsed_definition(model_id, lock)
        return definition.definition_fingerprint, request

    def __call__(self, owner_id, model_id, key):
        current, request = self._definition(model_id)
        worker = Path(__file__).with_name("provider_key_http.py")
        process = subprocess.Popen(
            [sys.executable, "-I", "-B", str(worker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        try:
            process.communicate(
                json.dumps(dict(request, key=key)).encode(), timeout=self.timeout
            )
        except BaseException:
            process.kill()
            process.wait(timeout=1)
            raise
        finally:
            process.stdin.close()
        if process.returncode == 1:
            raise ProviderKeyRefused()
        if process.returncode != 0:
            raise ValueError("The provider key could not be checked")
        if self._definition(model_id)[0] != current:
            raise ValueError("Current model definition changed")
        return VerifiedProviderKey(str(owner_id), model_id, current)

    def require_current(self, verification):
        if not transaction.get_connection().in_atomic_block:
            raise RuntimeError("Check model binding inside the storage transaction")
        if (
            self._definition(verification.model_id, lock=True)[0]
            != verification.definition_fingerprint
        ):
            raise ValueError("Current model definition changed")
