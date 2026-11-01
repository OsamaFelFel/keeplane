"""Decide within 200 ms whether a request is held to the detection class.

A request is held when personal data is found, and also whenever the check
cannot give a clean answer in time: no text was sent, the detector is not
installed, is still loading or failed to load, a check raises any error, or
the whole check takes longer than the limit. A request is never passed on
unchecked.

Long requests are checked in overlapping pieces, so the first piece that has
personal data ends the check early. The code-aware filter and the card and
phone rules always see the whole request, so cutting it never turns code
into prose or prose into code. A request whose pieces cannot all be checked
in time is held.

Request text stays in memory for the check only: it is never stored, logged,
included in an error or sent to another service.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

from . import code_aware, release_rules

LIMIT_SECONDS = 0.2
PIECE_CHARS = 2000
OVERLAP_CHARS = 200
WORKERS = 2
# Far longer than any request the limit allows checking; held without a check.
MAX_CHECK_CHARS = 100_000
RELOAD_AFTER_SECONDS = 60

# Why a request was or was not held. Never includes any request text.
FOUND, CLEAN, NOT_SENT, UNAVAILABLE, SLOW, FAILED = (
    "personal_data",
    "clean",
    "not_sent",
    "detector_unavailable",
    "detector_slow",
    "detector_failed",
)


@dataclass(frozen=True)
class Verdict:
    held: bool
    reason: str


class _Late(Exception):
    pass


def pieces(text, size=PIECE_CHARS, overlap=OVERLAP_CHARS):
    """Overlapping (start, end) offsets, cut at a line break or space if one is near."""
    n = len(text)
    if n <= size:
        return [(0, n)]
    out, start = [], 0
    while start < n:
        end = min(n, start + size)
        if end < n:
            cut = max(text.rfind("\n", start + size // 2, end), text.rfind(" ", start + size // 2, end))
            if cut > start:
                end = cut
        out.append((start, end))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return out


def _kept(text, mask, findings):
    findings = code_aware.filter_findings(text, findings, mask)
    return [f for f in findings if release_rules.keep_phone(text, f)]


def contains_personal_data(detector, text, deadline=None):
    """The whole check: detector, code-aware filter and card and phone rules."""
    if release_rules.mastercard_2_series(text):
        return True
    mask = code_aware.code_mask(text)
    for a, b in pieces(text):
        if deadline is not None and time.monotonic() > deadline:
            raise _Late()
        found = [
            {**f, "start": f["start"] + a, "end": f["end"] + a}
            for f in detector.find(text[a:b])
        ]
        if _kept(text, mask, found):
            return True
    if deadline is not None and time.monotonic() > deadline:
        raise _Late()
    return False


class Inspector:
    """Load the detector in the background and check requests against the limit."""

    def __init__(self, factory, *, limit=LIMIT_SECONDS, workers=WORKERS,
                 clock=time.monotonic):
        self._factory, self.limit, self._clock = factory, limit, clock
        self._lock = threading.Lock()
        self._detector = None
        self._loading = False
        self._failed_at = None
        self._pool = ThreadPoolExecutor(max_workers=workers,
                                        thread_name_prefix="keeplane-detection")

    def _load(self):
        try:
            detector = self._factory()
        except Exception:  # noqa: BLE001 - any load failure holds requests
            with self._lock:
                self._loading, self._failed_at = False, self._clock()
            return
        with self._lock:
            self._detector, self._loading = detector, False

    def detector(self):
        """The loaded detector, or None while it loads or after it failed to."""
        with self._lock:
            if self._detector is not None:
                return self._detector
            retry = self._failed_at is None or (
                self._clock() - self._failed_at >= RELOAD_AFTER_SECONDS
            )
            if not self._loading and retry:
                self._loading, self._failed_at = True, None
                threading.Thread(target=self._load, name="keeplane-detection-load",
                                 daemon=True).start()
            return None

    def check(self, text):
        if not isinstance(text, str):
            return Verdict(True, NOT_SENT)
        if len(text) > MAX_CHECK_CHARS:
            return Verdict(True, SLOW)
        detector = self.detector()
        if detector is None:
            return Verdict(True, UNAVAILABLE)
        deadline = time.monotonic() + self.limit
        try:
            future = self._pool.submit(contains_personal_data, detector, text, deadline)
        except RuntimeError:
            return Verdict(True, FAILED)
        try:
            found = future.result(timeout=max(0.0, deadline - time.monotonic()))
        except (FutureTimeout, _Late):
            future.cancel()
            return Verdict(True, SLOW)
        except Exception:  # noqa: BLE001 - any detector error holds the request
            return Verdict(True, FAILED)
        return Verdict(True, FOUND) if found else Verdict(False, CLEAN)


def request_text(messages):
    """All text a chat request carries, or None when some of it can't be read.

    Reads message content (a string or text parts), tool-call names and
    arguments. A part that is not text, such as an image, cannot be checked,
    so the request is treated as not checked and held.
    """
    if not isinstance(messages, list) or not messages:
        return None
    out = []
    for message in messages:
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        if isinstance(content, str):
            out.append(content)
        elif isinstance(content, list):
            for part in content:
                if (
                    not isinstance(part, dict)
                    or part.get("type") != "text"
                    or not isinstance(part.get("text"), str)
                ):
                    return None
                out.append(part["text"])
        elif content is not None:
            return None
        for call in message.get("tool_calls") or []:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict):
                return None
            for field in ("name", "arguments"):
                value = function.get(field)
                if isinstance(value, str):
                    out.append(value)
                elif value is not None:
                    return None
        name = message.get("name")
        if isinstance(name, str):
            out.append(name)
    return "\n\n".join(out)


_INSPECTOR = None
_INSPECTOR_LOCK = threading.Lock()


def inspector():
    """The process-wide inspector, built from the configured model."""
    global _INSPECTOR
    with _INSPECTOR_LOCK:
        if _INSPECTOR is None:
            from django.conf import settings

            from .engine import PresidioDetector

            model = settings.PERSONAL_DATA_MODEL
            _INSPECTOR = Inspector(lambda: PresidioDetector(model))
        return _INSPECTOR
