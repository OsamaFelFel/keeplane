"""Small agentgateway adapter for the model registry contract."""

import json
import os
import ssl
import time
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GATEWAY_CA_FILE = "KEEPLANE_GATEWAY_CA_FILE"
_contexts = {}


def gateway_tls_context():
    """The TLS trust for an https gateway: the system CAs plus the mounted CA.

    KEEPLANE_GATEWAY_CA_FILE names a PEM file (one CA or a bundle) for a
    customer-run gateway signed by a private CA. The file is checked on every
    call and reloaded when it changes, so a renewed or rotated CA in a mounted
    Secret is used without a restart. Raises OSError or ssl.SSLError when the
    file is set but cannot be read.
    """
    path = os.environ.get(GATEWAY_CA_FILE, "")
    if not path:
        return ssl.create_default_context()
    info = os.stat(path)
    stamp = (path, info.st_mtime_ns, info.st_size, info.st_ino)
    context = _contexts.get(stamp)
    if context is None:
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=path)
        _contexts.clear()
        _contexts[stamp] = context
    return context


class AgentgatewayModelAdapter:
    def __init__(self, base_url, runtime_key_file, admin_key_file):
        self.base_url = base_url.rstrip("/")
        self.runtime_key_file = runtime_key_file
        self.admin_key_file = admin_key_file

    def request(self, path, body=None, method=None, connection_retries=0, timeout=120):
        key_file = (
            self.admin_key_file if path.startswith("/api/") else self.runtime_key_file
        )
        try:
            key = Path(key_file).read_text().strip() if key_file else ""
        except OSError:
            key = ""
        if key_file and not key:
            return 503, {"error": "Gateway credential unavailable"}
        payload = None if body is None else json.dumps(body).encode()
        request = Request(
            self.base_url + path,
            data=payload,
            method=method or ("POST" if payload is not None else "GET"),
        )
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        if key:
            request.add_header("Authorization", "Bearer " + key)
        tls = {}
        if self.base_url.startswith("https:"):
            try:
                tls["context"] = gateway_tls_context()
            except (OSError, ssl.SSLError):
                return 503, {"error": "Gateway CA unavailable"}
        try:
            with urlopen(request, timeout=timeout, **tls) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            try:
                return error.code, json.load(error)
            except (ValueError, TypeError):
                return error.code, {"error": f"Gateway returned HTTP {error.code}"}
        except URLError as error:
            if connection_retries and isinstance(error.reason, ConnectionRefusedError):
                time.sleep(0.25)
                return self.request(path, body, method, connection_retries - 1, timeout)
            return 503, {"error": "Gateway unavailable"}
        except TimeoutError:
            return 503, {"error": "Gateway unavailable"}

    def models(self):
        return self.request("/v1/models", timeout=10)

    def resources(self):
        # A replica may briefly return 500 while reconnecting its model store.
        for attempt in range(3):
            status, result = self.request("/api/config/resources/llm.model", timeout=10)
            if status < 500 or attempt == 2:
                return status, result
            time.sleep(0.25)

    def delete_model(self, model_id):
        return self.request(
            "/api/config/resources/llm.model/" + quote(model_id, safe=""),
            method="DELETE",
        )

    def restore_model(self, value):
        """Write back a model definition removed by a removal that failed."""
        return self.request(
            "/api/config/resources/llm.model",
            {"resources": [{"value": value}]},
            "PUT",
        )
