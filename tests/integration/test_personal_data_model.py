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


def test_pm_02_works_offline_and_names_no_text(inspector, monkeypatch):
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("The detector tried to use the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    verdict = inspector.check("Send it to amara.okonkwo@example.com today")
    assert verdict.held and verdict.reason == "personal_data"
    assert "example.com" not in repr(verdict)
