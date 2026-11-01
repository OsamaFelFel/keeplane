"""Drop name and address findings that are explained by code.

The language model reads library names, algorithms named after people, time
zones and Java package names as people or places. This filter runs after the
detector and drops a name (PERSON) or address (ADDRESS) finding when every
name-like word in it is explained by code or by the allow list. Email, phone
and card findings are never touched.

A name-like word is a capitalised word such as "Amara" or "Mbeki-Rowe"; for
addresses, a US state code with ZIP or a UK postcode also counts. A finding
with no name-like word at all (for example "-A INPUT -s", "status=504" or
"3.6.3") is dropped.

A word is explained when it lies in one of these, or is on the allow list:

- a code span: text between backticks, a fenced block, or a line indented by a
  tab or four or more spaces. Inside a code span, string literals ("..." or
  '...') and comments (# or // to the end of the line) are NOT treated as code,
  because that is where personal data sits in pasted code;
- a stack-trace frame line (Java "at a.b.C.m(File.java:12)", Python
  'File "x.py", line 3') or the Python "Traceback" header;
- an import line (import, from ... import, using, package, require, #include);
- a dotted identifier such as java.lang or org.apache.http.impl.conn;
- a file path such as /srv/app/sync.py or src/app/main.ts;
- an IANA time-zone name such as Europe/Berlin or America/New_York.

The allow list is allow-list.txt beside this file. Pure Python. Matched text is
never logged.
"""

import re
from pathlib import Path

FILTERED_TYPES = {"PERSON", "ADDRESS"}


def load_allow_list(path=Path(__file__).with_name("allow-list.txt")):
    words = set()
    with open(path, encoding="utf-8") as source:
        for line in source:
            line = line.split("#", 1)[0].strip()
            if line:
                words.add(line.lower())
    return frozenset(words)


ALLOW = load_allow_list()

TZ_AREAS = ("Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|Europe|"
            "Indian|Pacific|Etc|US|Canada|Brazil|Mexico|Chile")
RE_TZ = re.compile(rf"\b(?:{TZ_AREAS})/[A-Za-z0-9_+\-]+(?:/[A-Za-z_\-]+)?")
RE_DOTTED = re.compile(r"(?<![\w.@-])[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+(?![\w@-])")
RE_PATH = re.compile(r"(?<![\w/])(?:~|\.{1,2})?/[\w.\-]+(?:/[\w.\-]+)*"
                     r"|(?<![\w/])[\w.\-]+(?:/[\w.\-]+)+\.[A-Za-z0-9]{1,5}\b")
RE_FRAME = re.compile(r"^[ \t]*(?:at [\w$.<>/]+\(.*\)|File \".*\", line \d+.*"
                      r"|Traceback \(most recent call last\):)[ \t]*$", re.M)
RE_IMPORT = re.compile(r"^[ \t]*(?:import\s+\S|from\s+\S+\s+import\s|using\s+[\w.]+;"
                       r"|package\s+[\w.]+;?|require[ (]|#include\s).*$", re.M)
RE_FENCE = re.compile(r"^[ \t]*```.*?(?:^[ \t]*```[ \t]*$|\Z)", re.M | re.S)
RE_TICK = re.compile(r"`[^`\n]+`")
RE_INDENTED = re.compile(r"^(?:\t| {4,}).*$", re.M)
RE_LITERAL = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")
RE_COMMENT = re.compile(r"(?:(?<=\s)|^)(?:#|//).*$", re.M)

RE_WORD = re.compile(r"[A-Z][a-z]+(?:['’-][A-Za-z]+)*")
RE_ADDRESS_CODE = re.compile(r"\b[A-Z]{2} \d{5}\b|\b[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}\b")


def _mark(mask, spans):
    for a, b in spans:
        mask[a:b] = [True] * (b - a)


def code_mask(text):
    """Per-character flags: True where the text is code, not prose or data."""
    n = len(text)
    span = [False] * n
    _mark(span, (m.span() for m in RE_FENCE.finditer(text)))
    _mark(span, (m.span() for m in RE_TICK.finditer(text)))
    _mark(span, (m.span() for m in RE_INDENTED.finditer(text)))
    data = [False] * n
    for rx in (RE_LITERAL, RE_COMMENT):
        _mark(data, (m.span() for m in rx.finditer(text)))
    mask = [span[i] and not data[i] for i in range(n)]
    for rx in (RE_FRAME, RE_IMPORT, RE_DOTTED, RE_PATH, RE_TZ):
        _mark(mask, (m.span() for m in rx.finditer(text)))
    return mask


def _allowed(word):
    w = word.lower()
    for suffix in ("'s", "’s"):
        w = w.removesuffix(suffix)
    return w in ALLOW


def keep(text, finding, mask=None):
    """True if the finding should still hold the request."""
    if finding["type"] not in FILTERED_TYPES:
        return True
    mask = code_mask(text) if mask is None else mask
    a, b = finding["start"], finding["end"]
    piece = text[a:b]
    words = [(a + m.start(), a + m.end(), m.group()) for m in RE_WORD.finditer(piece)]
    if finding["type"] == "ADDRESS":
        words += [(a + m.start(), a + m.end(), None) for m in RE_ADDRESS_CODE.finditer(piece)]
    if not words:
        return False
    for s, e, w in words:
        in_code = all(mask[i] for i in range(s, e))
        if not in_code and not (w and _allowed(w)):
            return True
    return False


def filter_findings(text, findings, mask=None):
    mask = code_mask(text) if mask is None else mask
    return [f for f in findings if keep(text, f, mask)]
