"""Read one model back from every configured gateway serving copy.

The copies share the gateway's model store, so a management write through the
gateway address reaches each copy on its own schedule. A change is confirmed
only when every listed copy reads back exactly the expected state: the same
definition and revision (its fingerprint) for a model being set up, or no
entry for a model being removed. A copy that cannot be read, or still reads
another state after the bounded wait, leaves the change unconfirmed.

Only management resource reads are sent. Nothing here writes to a copy,
reads another model's definition as authority or sends a model request.
"""

import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from model_registry.fingerprints import fingerprint

from .adapter import AgentgatewayModelAdapter

RESOURCES = "/api/config/resources/llm.model"
MAX_COPIES = 32


class GatewayCopiesUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class CopyReadback:
    total: int
    confirmed: int

    @property
    def complete(self):
        return self.confirmed == self.total

    def summary(self):
        return f"{self.confirmed} of {self.total} gateway copies confirmed it."


def copy_urls(value):
    """Parse GATEWAY_COPY_URLS; any unusable entry refuses the whole list."""
    urls = []
    for part in (value or "").split(","):
        url = part.strip().rstrip("/")
        if not url:
            continue
        origin = urlsplit(url)
        if (
            origin.scheme not in ("http", "https")
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.path
            or origin.query
            or origin.fragment
            or any(ord(char) < 33 or ord(char) > 126 for char in url)
        ):
            raise GatewayCopiesUnavailable("Gateway copy addresses are not valid")
        if url not in urls:
            urls.append(url)
    if len(urls) > MAX_COPIES:
        raise GatewayCopiesUnavailable("Too many gateway copies are listed")
    return urls


class GatewayCopies:
    """Every serving copy an operator lists, in addition to the gateway address."""

    def __init__(self, copies, *, attempts=10, pause=0.5, sleep=time.sleep):
        self.copies = list(copies)
        self.attempts, self.pause, self.sleep = attempts, pause, sleep
        # Set when the operator's list could not be used. Every change is then
        # unconfirmed rather than confirmed by fewer copies than are serving.
        self.misconfigured = False

    @classmethod
    def from_environment(cls, primary, environ=None):
        environ = os.environ if environ is None else environ
        try:
            urls = copy_urls(environ.get("GATEWAY_COPY_URLS", ""))
        except GatewayCopiesUnavailable:
            refused = cls([])
            refused.misconfigured = True
            return refused
        return cls(
            AgentgatewayModelAdapter(
                url, primary.runtime_key_file, primary.admin_key_file
            )
            for url in urls
        )

    @staticmethod
    def _reads(copy, model_id, expected, file_config):
        try:
            status, body = copy.request(RESOURCES, timeout=5, connection_retries=0)
        except Exception:  # noqa: BLE001 - an unreadable copy is unconfirmed
            return False
        if status != 200 or not isinstance(body, dict):
            return False
        rows = body.get("resources")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return False
        listed = [row for row in rows if row.get("id") == model_id]
        if expected is None:
            return not listed
        return len(listed) == 1 and fingerprint(model_id, rows, file_config) == expected

    def confirm(self, model_id, expected, file_config=None):
        """Wait until every copy reads `expected` (a fingerprint, or None for gone)."""
        if self.misconfigured:
            return CopyReadback(1, 0)
        confirmed = 0
        for attempt in range(self.attempts):
            if attempt:
                self.sleep(self.pause)
            # Every copy is read again on each pass: an earlier confirmation is
            # not kept if another write moved that copy on since.
            confirmed = sum(
                self._reads(copy, model_id, expected, file_config)
                for copy in self.copies
            )
            if confirmed == len(self.copies):
                break
        return CopyReadback(len(self.copies), confirmed)
