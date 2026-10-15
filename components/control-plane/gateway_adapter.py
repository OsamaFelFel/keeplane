"""Small agentgateway adapter for the model registry contract."""

import json
import time
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AgentgatewayModelAdapter:
    def __init__(self, base_url, runtime_key_file, admin_key_file):
        self.base_url = base_url.rstrip("/")
        self.runtime_key_file = runtime_key_file
        self.admin_key_file = admin_key_file

    def request(self, path, body=None, method=None, connection_retries=0, timeout=120):
        key_file = self.admin_key_file if path.startswith("/api/") else self.runtime_key_file
        try:
            key = Path(key_file).read_text().strip() if key_file else ""
        except OSError:
            key = ""
        if key_file and not key:
            return 503, {"error": "Gateway credential unavailable"}
        payload = None if body is None else json.dumps(body).encode()
        request = Request(self.base_url + path, data=payload,
                          method=method or ("POST" if payload is not None else "GET"))
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        if key:
            request.add_header("Authorization", "Bearer " + key)
        try:
            with urlopen(request, timeout=timeout) as response:
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
        return self.request("/api/config/resources/llm.model/" + quote(model_id, safe=""),
                            method="DELETE")
