"""The optional detector's pins, licence inventory and image target agree.

Cases PD-09 and PD-10 in tests/unit/personal-data-detection-cases.md.
"""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "components" / "control-plane"
LICENSES = ROOT / "licenses"


def pins():
    out = {}
    for line in (ROOT / "requirements-detection.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(
            r"([\w-]+)(?:==([\w.]+)| @ (https://\S+)) --hash=sha256:([a-f0-9]{64})", line
        )
        assert match, line
        out[match[1]] = (match[2] or match[3], match[4])
    return out


def normal(name):
    return name.lower().replace("_", "-")


# PD-09 Every pinned wheel is in the inventory with the same version and hash,
# with a source archive or release, and the measured detector versions.
def test_pd_09_pins_match_the_licence_inventory():
    inventory = json.loads((LICENSES / "personal-data-detection.json").read_text())
    rows = {normal(row["name"]): row for row in inventory["packages"]}
    declared = pins()
    assert set(rows) == set(declared)
    for name, (version, digest) in declared.items():
        row = rows[name]
        assert row["wheel"]["sha256"] == digest
        assert version in (row["version"], row["wheel"]["url"])
        assert row["source"] and row["source"]["url"].startswith("https://")
    assert declared["presidio-analyzer"][0] == "2.2.364"
    assert declared["spacy"][0] == "3.8.18"
    assert "en_core_web_lg-3.8.0" in declared["en-core-web-lg"][0]
    # The app's own packaging pin stays; detection does not replace it.
    assert "packaging" not in declared
    notice = rows["presidio-analyzer"]["supplemental_notice"]
    text = (LICENSES / notice["file"]).read_bytes()
    assert hashlib.sha256(text).hexdigest() == notice["sha256"]
    assert b"MIT License" in text


# PD-10 Only the explicit detection target installs the detector; the default
# image (the last stage) stays without it and the notices ship with it.
def test_pd_10_detection_is_an_explicit_image_target():
    dockerfile = (ROOT / "Dockerfile").read_text()
    stages = re.findall(r"^FROM \S+ AS (\S+)$", dockerfile, re.M)
    assert "detection" in stages and stages[-1] == "preview"
    section = dockerfile.split("AS detection", 1)[1].split("\nFROM ", 1)[0]
    assert "--require-hashes --no-deps" in section
    assert "requirements-detection.txt" in section
    for name in ("personal-data-detection.md", "personal-data-detection.json",
                 "presidio-analyzer-2.2.364-LICENSE.txt"):
        assert name in section
    assert dockerfile.count("requirements-detection.txt") == 1
