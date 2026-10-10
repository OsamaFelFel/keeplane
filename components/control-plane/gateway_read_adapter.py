"""Read-only adapter for the agentgateway model registry."""

import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AgentgatewayModelReader:
    def __init__(self, base_url, runtime_key_file, admin_key_file):
        self.base_url = base_url.rstrip("/")
        self.runtime_key_file = runtime_key_file
        self.admin_key_file = admin_key_file

    def _read(self, path, key_file):
        try:
            key = Path(key_file).read_text().strip() if key_file else ""
        except OSError:
            key = ""
        if key_file and not key:
            return 503, {"error": "Gateway credential unavailable"}
        request = Request(self.base_url + path)
        if key:
            request.add_header("Authorization", "Bearer " + key)
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            try:
                return error.code, json.load(error)
            except (ValueError, TypeError):
                return error.code, {"error": f"Gateway returned HTTP {error.code}"}
        except (URLError, TimeoutError):
            return 503, {"error": "Gateway unavailable"}

    def models(self):
        return self._read("/v1/models", self.runtime_key_file)

    def resources(self):
        # A replica may briefly return 500 while reconnecting its model store.
        for attempt in range(3):
            status, result = self._read("/api/config/resources/llm.model", self.admin_key_file)
            if status < 500 or attempt == 2:
                return status, result
            time.sleep(0.25)
