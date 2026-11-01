"""Detection rules, request text and the 200 ms hold rule, with a fake detector.

Cases: tests/unit/personal-data-detection-cases.md. No language model is
loaded here; tests/integration/test_personal_data_model.py runs the real one.
"""

import logging
import threading
import time

import pytest
from personal_data import code_aware, release_rules
from personal_data.inspection import (
    CLEAN,
    FAILED,
    FOUND,
    MAX_CHECK_CHARS,
    NOT_SENT,
    SLOW,
    UNAVAILABLE,
    Inspector,
    contains_personal_data,
    pieces,
    request_text,
)

# Every value is invented: names, fiction-range phones and example.com emails.
NAME = "Amara Okonkwo-Reyes"


class Fake:
    """Finds the listed words as the given types; optional delay or error."""

    def __init__(self, words=None, delay=0.0, error=None):
        self.words, self.delay, self.error = words or {}, delay, error
        self.calls = []

    def find(self, text):
        self.calls.append(len(text))
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        out = []
        for word, kind in self.words.items():
            start = text.find(word)
            while start >= 0:
                out.append({"type": kind, "start": start, "end": start + len(word)})
                start = text.find(word, start + 1)
        return out


def ready(detector, **options):
    inspector = Inspector(lambda: detector, **options)
    inspector.detector()
    for _ in range(200):
        if inspector.detector() is not None:
            return inspector
        time.sleep(0.005)
    raise AssertionError("fake detector did not load")


def make_card(prefix):
    body = prefix + "0" * (15 - len(prefix))
    return next(body + d for d in "0123456789" if release_rules.luhn_ok(body + d))


# PD-01 Mastercard 2-series cards are found; numbers outside the range are not.
def test_pd_01_mastercard_2_series_cards():
    lo, hi = make_card("2221"), make_card("2720")
    assert len(release_rules.mastercard_2_series(lo)) == 1
    assert len(release_rules.mastercard_2_series(hi)) == 1
    grouped = " ".join(hi[i:i + 4] for i in range(0, 16, 4))
    assert len(release_rules.mastercard_2_series("card " + grouped + " ok")) == 1
    for other in (make_card("2220"), make_card("2721")):
        assert release_rules.mastercard_2_series(other) == []
    bad = lo[:-1] + str((int(lo[-1]) + 1) % 10)
    assert release_rules.mastercard_2_series(bad) == []
    assert release_rules.mastercard_2_series("x" + lo + "1") == []


def phone(text, value):
    a = text.index(value)
    return {"type": "PHONE", "start": a, "end": a + len(value)}


# PD-02 IP addresses and build numbers are not phones; real phones stay phones.
@pytest.mark.parametrize("text,value", [
    ("iptables -A INPUT -s 172.17.119.91/32 -p tcp", "172.17.119.91"),
    ("Build 1434-937-3750 failed at step 3", "1434-937-3750"),
    ("release v2024-118-0042 is out", "2024-118-0042"),
    ("build #2024-118-0042 passed", "2024-118-0042"),
    ("version: 3.14.1592 shipped", "3.14.1592"),
    ("first line\nhost 10.0.0.12:8080 down", "10.0.0.12"),
])
def test_pd_02_ip_and_build_numbers_are_not_phones(text, value):
    assert not release_rules.keep_phone(text, phone(text, value))


@pytest.mark.parametrize("text,value", [
    ("Call me at my job 020 7946 0958", "020 7946 0958"),
    ("Job: 07700 900123 is my mobile", "07700 900123"),
    ("version: 555-0142", "555-0142"),
    ("Contact Rev 07700 900123", "07700 900123"),
    ("Build team: call 0113 496 0123", "0113 496 0123"),
    ("build: +44 113 496 0123", "+44 113 496 0123"),
    ("version 1-555-555-0142", "1-555-555-0142"),
    ("release 2024-118-0042 by phone", "2024-118-0042"),
    ("build 555.123.4567", "555.123.4567"),
    ("Rebuild failed, call 555-0142 now", "555-0142"),
    ("999.300.400.500 is not an address", "999.300.400.500"),
])
def test_pd_02_real_phones_are_kept(text, value):
    assert release_rules.keep_phone(text, phone(text, value))


def name_finding(text, word, kind="PERSON"):
    a = text.index(word)
    return {"type": kind, "start": a, "end": a + len(word)}


# PD-03 Names in code, traces, package paths and time zones are not personal data.
@pytest.mark.parametrize("text,word,kind", [
    ("Run `Okonkwo.parse(x)` again", "Okonkwo", "PERSON"),
    ('  File "/srv/Amara/app.py", line 3', "Amara", "PERSON"),
    ("at org.Amara.Sync.run(Sync.java:12)", "Amara", "PERSON"),
    ("set TZ to Europe/Berlin today", "Europe/Berlin", "ADDRESS"),
    ("import Reyes from 'reyes'", "Reyes", "PERSON"),
    ("Kafka keeps lagging", "Kafka", "PERSON"),
    ("use Dijkstra's algorithm", "Dijkstra's", "PERSON"),
])
def test_pd_03_code_is_not_personal_data(text, word, kind):
    assert not code_aware.keep(text, name_finding(text, word, kind))


@pytest.mark.parametrize("text,word", [
    (f"Please email {NAME} about it", NAME),
    ('```\nowner = "Amara Okonkwo"\n```', "Amara Okonkwo"),
    ("```\nx = 1  # ask Amara Okonkwo\n```", "Amara Okonkwo"),
    ("Cassandra Okafor approved it", "Cassandra Okafor"),
])
def test_pd_03_names_in_prose_literals_and_comments_are_kept(text, word):
    assert code_aware.keep(text, name_finding(text, word))


def test_pd_03_email_phone_and_card_findings_are_never_filtered():
    text = "`a@example.com`"
    for kind in ("EMAIL", "PHONE", "CARD"):
        assert code_aware.keep(text, {"type": kind, "start": 1, "end": 14})


# PD-04 Long requests are checked in overlapping pieces covering every character.
def test_pd_04_pieces_cover_the_text_with_overlap():
    text = ("word " * 3000).strip()
    spans = pieces(text, size=2000, overlap=200)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
        assert a2 < b1 and b1 - a2 <= 200 + 1 and b2 > b1
        assert all(b - a <= 2000 for a, b in spans)
    assert pieces("short") == [(0, 5)]
    assert pieces("x" * 4500, size=2000, overlap=200)[-1][1] == 4500


def test_pd_04_a_value_across_a_cut_is_found_in_the_overlap():
    fake = Fake({"amara@example.com": "EMAIL"})
    text = "a " * 995 + "amara@example.com " + "b " * 2000
    assert contains_personal_data(fake, text)


def test_pd_04_the_first_piece_with_personal_data_ends_the_check():
    fake = Fake({"amara@example.com": "EMAIL"})
    text = "amara@example.com " + "word " * 4000
    assert contains_personal_data(fake, text)
    assert len(fake.calls) == 1


def test_pd_04_code_context_comes_from_the_whole_request():
    # The fence opens in the first piece and closes far later; a name inside
    # it, outside literals, stays code even though its piece has no fence.
    body = "\n".join(f"x = compute({i})" for i in range(400))
    text = "```\n" + body + "\nKafka.Producer.send(Okonkwo)\n" + body + "\n```\n"
    fake = Fake({"Okonkwo": "PERSON"})
    assert not contains_personal_data(fake, text)


# PD-05 Clean text passes; found personal data holds.
def test_pd_05_verdicts_for_found_and_clean():
    inspector = ready(Fake({NAME: "PERSON"}))
    held = inspector.check(f"Ask {NAME} to review")
    assert held.held and held.reason == FOUND
    clean = inspector.check("Refactor the parser please")
    assert not clean.held and clean.reason == CLEAN


def test_pd_05_a_2_series_card_holds_without_the_detector_finding_it():
    inspector = ready(Fake())
    assert inspector.check("pay with " + make_card("2221")).held


# PD-06 Anything that is not a clean answer within the limit holds the request.
def test_pd_06_slower_than_the_limit_is_held():
    inspector = ready(Fake(delay=0.4), limit=0.05)
    start = time.monotonic()
    verdict = inspector.check("Refactor the parser please")
    assert verdict.held and verdict.reason == SLOW
    assert time.monotonic() - start < 0.3


def test_pd_06_long_requests_that_cannot_finish_are_held():
    inspector = ready(Fake(delay=0.03), limit=0.1)
    verdict = inspector.check("word " * 6000)
    assert verdict.held and verdict.reason == SLOW
    assert inspector.check("x" * (MAX_CHECK_CHARS + 1)).reason == SLOW


def test_pd_06_a_detector_error_is_held():
    inspector = ready(Fake(error=RuntimeError("model crashed")))
    verdict = inspector.check("Refactor the parser please")
    assert verdict.held and verdict.reason == FAILED


def test_pd_06_a_detector_still_loading_or_not_installed_is_held():
    gate = threading.Event()

    def slow_load():
        gate.wait(2)
        return Fake()

    loading = Inspector(slow_load)
    verdict = loading.check("Refactor the parser please")
    assert verdict.held and verdict.reason == UNAVAILABLE
    gate.set()

    def missing():
        raise ImportError("not installed")

    broken = Inspector(missing)
    for _ in range(3):
        assert broken.check("Refactor the parser please").reason == UNAVAILABLE
        time.sleep(0.01)


def test_pd_06_text_that_was_not_sent_is_held():
    inspector = ready(Fake())
    assert inspector.check(None).held and inspector.check(None).reason == NOT_SENT


# PD-07 All message text is read; anything unreadable holds the request.
def test_pd_07_request_text_reads_every_text_part():
    text = request_text([
        {"role": "system", "content": "Be brief"},
        {"role": "user", "content": [{"type": "text", "text": "Ask " + NAME}]},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "1", "type": "function",
             "function": {"name": "lookup", "arguments": '{"who": "a@example.com"}'}},
        ]},
        {"role": "tool", "content": "phone 020 7946 0958", "tool_call_id": "1"},
    ])
    for piece in ("Be brief", NAME, "lookup", "a@example.com", "020 7946 0958"):
        assert piece in text


@pytest.mark.parametrize("messages", [
    None, [], "text", [1], [{"content": 5}],
    [{"content": [{"type": "image_url", "image_url": {"url": "data:"}}]}],
    [{"content": "x", "tool_calls": [{"function": "bad"}]}],
    # Fields Keeplane doesn't read never pass unchecked.
    [{"role": "user", "content": "x", "audio": {"data": "AAAA"}}],
    [{"role": "user", "content": "x", "metadata": {"owner": "Amara"}}],
    [{"role": "user", "content": [{"type": "text", "text": "x", "extra": "Amara"}]}],
    [{"role": "assistant", "tool_calls": {"id": "1"}}],
    [{"role": "assistant", "tool_calls": "call"}],
    [{"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "f", "x": "y"}}]}],
    [{"role": "assistant", "function_call": "lookup"}],
    [{"role": "assistant", "refusal": 5}],
    [{"role": 5, "content": "x"}],
])
def test_pd_07_unreadable_messages_are_not_checked(messages):
    assert request_text(messages) is None


def test_pd_07_legacy_function_calls_and_refusals_are_read():
    text = request_text([
        {"role": "assistant", "content": None, "refusal": "I won't email " + NAME,
         "function_call": {"name": "lookup", "arguments": '{"who": "a@example.com"}'}},
        {"role": "assistant", "content": [{"type": "refusal", "refusal": "No, 020 7946 0958"}]},
        {"role": "function", "name": "lookup", "content": "done", "metadata": None},
    ])
    for piece in (NAME, "lookup", "a@example.com", "020 7946 0958", "done"):
        assert piece in text


def test_pd_07_a_non_list_tool_calls_field_holds_rather_than_errors():
    inspector = ready(Fake())
    for calls in ("call", {"id": "1"}, 7):
        verdict = inspector.check(request_text([{"role": "assistant", "tool_calls": calls}]))
        assert verdict.held and verdict.reason == NOT_SENT


# PD-08 Request text never reaches logs or verdicts.
def test_pd_08_no_request_text_in_logs_or_verdicts(caplog):
    caplog.set_level(logging.DEBUG)
    secret = "amara.okonkwo@example.com"
    for detector in (Fake({secret: "EMAIL"}), Fake(error=ValueError(secret))):
        verdict = ready(detector).check("mail " + secret)
        assert secret not in repr(verdict)
    assert secret not in caplog.text
