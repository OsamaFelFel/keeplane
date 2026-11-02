"""The shipped detector meets the release-1 bar on both English sets.

Cases: tests/integration/personal-data-model-cases.md. Needs the optional
detector install (components/control-plane/requirements-detection.txt or the
same pinned versions) with the en_core_web_lg 3.8.0 model; skipped otherwise.
Run it explicitly with ``-m optional``. Output is counts and case IDs only,
never request text.
"""

import json
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.optional

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "personal_data"
MODEL = "en_core_web_lg"

# The release-1 bar: at most this many missed / clean requests held, per set.
BAR = {
    "english-set.json": ("2026-10-31.1", 4, 1),
    "english-heldout-set.json": ("2026-10-31.h1", 11, 14),
}


@pytest.fixture(scope="module")
def inspector():
    pytest.importorskip("presidio_analyzer")
    spacy = pytest.importorskip("spacy")
    if not spacy.util.is_package(MODEL):
        pytest.skip("The en_core_web_lg model is not installed")
    from personal_data.engine import PresidioDetector
    from personal_data.inspection import Inspector

    inspector = Inspector(lambda: PresidioDetector(MODEL))
    deadline = time.monotonic() + 120
    while inspector.detector() is None:
        if time.monotonic() > deadline:
            pytest.fail("The detector did not load")
        time.sleep(0.2)
    return inspector


@pytest.mark.parametrize("name", sorted(BAR))
def test_pm_01_release_bar_on_both_english_sets(inspector, name):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    version, max_missed, max_held = BAR[name]
    assert data["version"] == version
    missed, held, slow = [], [], 0
    for case in data["cases"]:
        verdict = inspector.check(case["text"])
        slow += verdict.reason == "detector_slow"
        if case["kind"] == "positive" and not verdict.held:
            missed.append(case["id"])
        elif case["kind"] == "clean" and verdict.held:
            held.append(case["id"])
    print(json.dumps({"set": name, "version": version, "missed": len(missed),
                      "held_clean": len(held), "slow": slow,
                      "missed_cases": missed, "held_cases": held}))
    assert len(missed) <= max_missed
    assert len(held) <= max_held


# Missed personal-data requests per kind when the bar was measured: the
# detector must do at least as well for each of the five kinds (Spec 005 ST20
# "What detection finds"), not only in total.
MISSED_BY_KIND = {
    "english-set.json": {"PERSON": 2, "ADDRESS": 2},
    "english-heldout-set.json": {"PERSON": 4, "ADDRESS": 6, "CARD": 1},
}
KINDS = ("PERSON", "ADDRESS", "EMAIL", "PHONE", "CARD")
# Clean requests shaped like code (Spec 005 ST20 "Code isn't personal data"),
# by the sets' form names, and how many of each were held when measured.
CODE_FORMS = {
    "english-set.json": {"code": 0, "trace": 0, "config": 0, "log": 0, "region": 0},
    "english-heldout-set.json": {
        "trace": 0, "import": 0, "path": 0, "code_tick": 0, "code_fence": 0,
        "cli": 0, "config": 0, "log": 0, "timezone": 1,
    },
}


def verdicts(inspector, name):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return [(case, inspector.check(case["text"]).held) for case in data["cases"]]


@pytest.mark.parametrize("name", sorted(BAR))
def test_pm_03_each_kind_of_personal_data_is_found(inspector, name):
    missed = dict.fromkeys(KINDS, 0)
    seen = dict.fromkeys(KINDS, 0)
    for case, held in verdicts(inspector, name):
        if case["kind"] != "positive":
            continue
        for kind in {item["type"] for item in case["expect"]}:
            seen[kind] += 1
            missed[kind] += not held
    print(json.dumps({"set": name, "positives": seen, "missed": missed}))
    for kind in KINDS:
        assert seen[kind] >= 20, kind
        assert missed[kind] <= MISSED_BY_KIND[name].get(kind, 0), kind


@pytest.mark.parametrize("name", sorted(BAR))
def test_pm_04_code_shaped_requests_are_not_held(inspector, name):
    held = dict.fromkeys(CODE_FORMS[name], 0)
    seen = dict.fromkeys(CODE_FORMS[name], 0)
    for case, was_held in verdicts(inspector, name):
        form = case["form"].rsplit("-", 1)[0]
        if case["kind"] == "clean" and form in held:
            seen[form] += 1
            held[form] += was_held
    print(json.dumps({"set": name, "clean": seen, "held": held}))
    for form, limit in CODE_FORMS[name].items():
        assert seen[form] > 0, form
        assert held[form] <= limit, form


def test_pm_02_works_offline_and_names_no_text(inspector, monkeypatch):
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("The detector tried to use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    verdict = inspector.check("Send it to amara.okonkwo@example.com today")
    assert verdict.held and verdict.reason == "personal_data"
    assert "example.com" not in repr(verdict)
