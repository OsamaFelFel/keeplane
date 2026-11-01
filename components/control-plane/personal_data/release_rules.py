"""Card and phone rules applied after the detector and the code-aware filter.

1. Mastercard 2-series cards. The detector's card pattern covers numbers
   starting with 1, 3, 4, 5 and 6, but not Mastercard's 2221 to 2720 range.
   This adds a CARD finding for a 16-digit number in that range, written
   plainly or in groups of four separated by single spaces or hyphens, when its
   Luhn check passes. Numbers already found are not added twice.

2. IP addresses and build or version numbers are not phones. A PHONE finding
   is dropped when it lies inside an IPv4 address (four dot-separated parts of
   0 to 255, optionally with /prefix or :port), or when both hold:

   - it comes straight after the word "build" or "version" (optionally
     followed by "#", "no." or ":"), or straight after a "v" with no space
     (v2024-118-0042); and
   - the number has a build-like shape: it does not start with 0 or +, it is
     only digits split by dots or hyphens, and its groups are not those of a
     North American phone (3-4, 3-3-4 or 1-3-3-4).

   So "Build 1434-937-3750" and "version: 3.14.1592" are dropped, but
   "version: 555-0142", "build 555.123.4567" and any number starting with 0
   or + are kept whatever word comes before them.

Every other finding is untouched. Pure Python. Matched text is never logged.
"""

import re

CARD_2_SERIES = re.compile(
    r"(?<![\d-])(2[2-7]\d{2})([ -]?)(\d{4})\2(\d{4})\2(\d{4})(?![\d-])")

RE_IPV4 = re.compile(
    r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:/\d{1,2}|:\d{1,5})?(?![\d.])")

BUILD_WORDS = ("build", "version")
RE_BUILD_BEFORE = re.compile(
    r"(?:^|[^\w])(?:" + "|".join(BUILD_WORDS) + r")(?:\s*(?:#|no\.|:))?\s+$"
    r"|(?:^|[^\w])(?:" + "|".join(BUILD_WORDS) + r")\s*(?:#|no\.|:)$",
    re.I)
RE_V_PREFIX = re.compile(r"(?:^|[^\w])v$", re.I)
RE_BUILD_NUMBER = re.compile(r"[1-9]\d*(?:[.-]\d+)+")
NANP_GROUPS = ([3, 4], [3, 3, 4], [1, 3, 3, 4])


def luhn_ok(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def mastercard_2_series(text):
    """CARD findings for Luhn-valid 16-digit numbers in 2221 to 2720."""
    out = []
    for m in CARD_2_SERIES.finditer(text):
        digits = m.group(1) + m.group(3) + m.group(4) + m.group(5)
        if 2221 <= int(digits[:4]) <= 2720 and luhn_ok(digits):
            out.append({"type": "CARD", "start": m.start(), "end": m.end()})
    return out


def _is_ip(text, a, b):
    return any(m.start() <= a and b <= m.end() for m in RE_IPV4.finditer(text))


def _build_shape(number):
    if number[:1] in ("0", "+") or not RE_BUILD_NUMBER.fullmatch(number):
        return False
    return [len(g) for g in re.split(r"[.-]", number)] not in NANP_GROUPS


def _is_build(text, a, b):
    before = text[max(0, a - 24):a]
    after_word = RE_BUILD_BEFORE.search(before) or RE_V_PREFIX.search(before)
    return bool(after_word) and _build_shape(text[a:b])


def _is_ip_near(text, a, b):
    # Only the surrounding line can hold the IPv4 address that contains a finding.
    start = text.rfind("\n", 0, a) + 1
    end = text.find("\n", b)
    end = len(text) if end < 0 else end
    return _is_ip(text[start:end], a - start, b - start)


def keep_phone(text, finding):
    """False when a PHONE finding is an IPv4 address or a build/version number."""
    if finding["type"] != "PHONE":
        return True
    a, b = finding["start"], finding["end"]
    return not (_is_ip_near(text, a, b) or _is_build(text, a, b))


def apply(text, findings):
    """Drop IP and build-number phones, then add missing 2-series cards."""
    kept = [f for f in findings if keep_phone(text, f)]
    cards = [f for f in kept if f["type"] == "CARD"]
    for c in mastercard_2_series(text):
        if not any(f["start"] < c["end"] and c["start"] < f["end"] for f in cards):
            kept.append(c)
    return kept
