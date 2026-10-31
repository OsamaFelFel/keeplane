"""Read one model back from every configured gateway serving copy.

The copies share the gateway's model store, so a management write through the
gateway address reaches each copy on its own schedule. A change is confirmed
only when every listed copy reads back exactly the expected state: the same
definition and revision (its fingerprint) for a model being set up, or no
entry for a model being removed. A copy that cannot be read, or still reads
another state when the overall deadline passes, leaves the change
unconfirmed.

A file-owned preview model is defined by the gateway's mounted file, not the
shared store, and never appears in the resource listing. For it a copy
confirms when it answers the listing and holds no store entry that would
replace the file's definition; the expected fingerprint is the file's digest.

Only management resource reads are sent. Nothing here writes to a copy,
reads another model's definition as authority or sends a model request.
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from urllib.parse import urlsplit

from model_registry.fingerprints import fingerprint

from .adapter import AgentgatewayModelAdapter

RESOURCES = "/api/config/resources/llm.model"
MAX_COPIES = 32
# The whole check, across every pass and copy, ends well inside the admin
# dialog's 10-second no-answer limit.
DEADLINE_SECONDS = 5.0
FILE_OWNED = "file-owned:"

log = logging.getLogger(__name__)


class GatewayCopiesUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class CopyReadback:
    total: int
    confirmed: int
    # The operator's copy list could not be used, so nothing can be confirmed.
    misconfigured: bool = False

    @property
    def complete(self):
        return not self.misconfigured and self.confirmed == self.total


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

    def __init__(
        self,
        copies,
        *,
        deadline=DEADLINE_SECONDS,
        pause=0.5,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.copies = list(copies)
        self.deadline, self.pause = deadline, pause
        self.sleep, self.clock = sleep, clock
        # Set when the operator's list could not be used. Every change that
        # needs a readback is then unconfirmed rather than confirmed by fewer
        # copies than are serving.
        self.misconfigured = False

    @classmethod
    def from_environment(cls, primary, environ=None):
        environ = os.environ if environ is None else environ
        try:
            urls = copy_urls(environ.get("GATEWAY_COPY_URLS", ""))
        except GatewayCopiesUnavailable as error:
            log.warning("GATEWAY_COPY_URLS is refused: %s", error)
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
    def _reads(copy, model_id, expected, file_config, timeout):
        try:
            status, body = copy.request(
                RESOURCES, timeout=timeout, connection_retries=0
            )
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
        if expected.startswith(FILE_OWNED):
            return not listed and fingerprint(model_id, rows, file_config) == expected
        return len(listed) == 1 and fingerprint(model_id, rows, file_config) == expected

    def confirm(self, model_id, expected, file_config=None):
        """Wait until every copy reads `expected` (a fingerprint, or None for gone)."""
        if self.misconfigured:
            log.warning(
                "Model change for %s refused: GATEWAY_COPY_URLS is invalid", model_id
            )
            return CopyReadback(0, 0, misconfigured=True)
        total = len(self.copies)
        if not total:
            return CopyReadback(0, 0)
        end = self.clock() + self.deadline
        confirmed = 0
        pool = ThreadPoolExecutor(max_workers=total)
        try:
            while True:
                remaining = end - self.clock()
                if remaining <= 0:
                    break
                # Every copy is read again, in parallel, on each pass: an
                # earlier confirmation is not kept if another write moved that
                # copy on since. No read outlives the deadline.
                futures = [
                    pool.submit(
                        self._reads, copy, model_id, expected, file_config, remaining
                    )
                    for copy in self.copies
                ]
                done, _ = wait(futures, timeout=remaining)
                confirmed = sum(1 for future in done if future.result() is True)
                if confirmed == total or end - self.clock() <= self.pause:
                    break
                self.sleep(self.pause)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return CopyReadback(total, confirmed)
