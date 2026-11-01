""""Held-back requests" Audit records: one per request detection holds back.

Spec 006 ST21, ADR 025 and governance issue #29. The plain-English cases are
in held-request-record-cases.md. A deterministic fake stands in for the
detector, as in test_personal_data_routing.py.
"""

import json
import logging
import re
from unittest.mock import patch

import pytest
from audit.models import AuditRecord
from data_classes import services as class_services
from django.db import OperationalError
from django.test import Client
from model_registry import held_request_records, runtime_callback
from personal_data.inspection import (
    FAILED,
    FOUND,
    NOT_SENT,
    SLOW,
    UNAVAILABLE,
    Verdict,
)

from tests.integration.test_installed_runtime import send as send_managed

pytest_plugins = ("tests.integration.test_installed_runtime",)

KIND = "held_requests"
LOGGER = "model_registry.held_request_records"
# Invented values on reserved ranges and domains.
EMAIL = "amara.okonkwo@example.com"
PROMPT = f"Write to {EMAIL} about invoice 4711"
SHARED = "/internal/runtime/authorize"
ALLOWED = (
    r"Request HR-[0-9a-f]{12} held back as Confidential \(Personal data detected\); "
    r"project Callback; approved model private"
)


class FakeInspector:
    def __init__(self):
        self.verdict = None

    def check(self, text):
        if self.verdict is not None:
            return self.verdict
        if text is None:
            return Verdict(True, NOT_SENT)
        return Verdict(True, FOUND) if EMAIL in text else Verdict(False, "clean")


def with_detection(f, monkeypatch):
    f.fake = FakeInspector()
    monkeypatch.setattr(runtime_callback, "inspector", lambda: f.fake)
    monkeypatch.setattr(class_services, "detection_available", lambda: True)
    f.stores.classes.set_detection({"enabled": True})
    return f


@pytest.fixture
def managed(installed, monkeypatch):
    return with_detection(installed, monkeypatch)


@pytest.fixture
def customer_run(callback, monkeypatch):
    monkeypatch.setenv("GATEWAY_MODE", "existing")
    return with_detection(callback, monkeypatch)


def messages(text=PROMPT):
    return [{"role": "user", "content": text}]


def entry(f, text=PROMPT, **changes):
    return send_managed(f, messages=messages(text), **changes)


def selected(f, text=PROMPT, **changes):
    return send_managed(f, True, messages=messages(text), **changes)


def shared(f, final=False, text=PROMPT, model="private", token=None, project=None):
    body = {
        "project_id": project or f.project,
        "model_id": model,
        "messages": messages(text),
    }
    return f.client.post(
        SHARED + ("/selected" if final else ""),
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + (token or f.token),
        HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=f.key,
    )


def held(f):
    return f.stores.audit.records(kind=KIND, page_size=50)["records"]


def switch_on(f):
    f.stores.audit.set_option(KIND, True)


def test_hr_01_after_install_nothing_is_recorded(managed):
    f = managed
    assert f.stores.audit.options()[KIND] is False
    assert entry(f).status_code == 200
    assert selected(f).status_code == 200
    assert AuditRecord.objects.count() == 0


def test_hr_02_one_record_per_held_request_with_its_details(managed):
    f = managed
    switch_on(f)
    for _ in range(2):
        # Entry check at the route, then the final check once per attempt:
        # the first try and two retries.
        assert entry(f).status_code == 200
        for _attempt in range(3):
            response = selected(f)
            assert response.status_code == 200
            assert set(response.json()) == {"actor_id", "project_id", "model_id"}
    rows = held(f)
    assert len(rows) == 2
    for row in rows:
        assert row["kind"] == KIND
        assert row["who"] == "callback-developer"
        assert re.fullmatch(ALLOWED, row["what"]), row["what"]
        assert row["when"].endswith("+00:00")
    # Each held request has its own reference.
    assert rows[0]["what"][:15] != rows[1]["what"][:15]
    stored = AuditRecord.objects.filter(kind=KIND).first()
    assert stored.actor_id == f.actor["id"]
    audit = f.stores.audit
    assert audit.records(kind=KIND, search="held back as confidential")["total"] == 2
    assert audit.records(kind=KIND, search=rows[0]["what"][8:23])["total"] == 1
    assert audit.records(kind="model_answers")["total"] == 0


def test_hr_03_a_held_request_refused_for_its_model_is_recorded(managed):
    f = managed
    switch_on(f)
    # Hold requests to Public: the installed model is approved for Confidential only.
    f.stores.classes.set_detection({"enabled": True, "class_id": "public"})
    response = entry(f)
    assert response.status_code == 403
    assert "nothing was sent" in response.json()["error"]
    [row] = held(f)
    assert re.fullmatch(
        r"Request HR-[0-9a-f]{12} held back as Public \(Personal data detected\); "
        r"project Callback; model private isn't approved for it, nothing was sent",
        row["what"],
    )


def test_hr_04_clean_and_undecided_requests_write_nothing(managed):
    f = managed
    switch_on(f)
    assert entry(f, "Refactor the parser").status_code == 200
    assert selected(f, "Refactor the parser").status_code == 200
    # Refused before any decision: no hold was made.
    assert entry(f, model_id="public").status_code == 403
    f.stores.identity.logout(f.token)
    assert entry(f).status_code == 401
    assert AuditRecord.objects.filter(kind=KIND).count() == 0


def test_hr_05_detection_off_writes_nothing(managed):
    f = managed
    switch_on(f)
    f.stores.classes.set_detection({"enabled": False})
    assert entry(f).status_code == 200
    f.stores.classes.set_detection({"enabled": True})
    f.stores.classes.set_enabled(False)
    assert entry(f).status_code == 200
    assert AuditRecord.objects.filter(kind=KIND).count() == 0


@pytest.mark.parametrize(
    "verdict, why",
    [
        (Verdict(True, FOUND), "Personal data detected"),
        (Verdict(True, NOT_SENT), "Request couldn't be read"),
        (Verdict(True, UNAVAILABLE), "Detection was down"),
        (Verdict(True, SLOW), "Detection took longer than 200 ms"),
        (Verdict(True, FAILED), "Detection failed"),
        (Verdict(True, "something new"), "Detection failed"),
    ],
)
def test_hr_06_each_reason_is_named(managed, verdict, why):
    f = managed
    switch_on(f)
    f.fake.verdict = verdict
    assert entry(f, "Refactor the parser").status_code == 200
    [row] = held(f)
    assert f"held back as Confidential ({why});" in row["what"]


def test_hr_06_unreadable_parts_are_also_named(managed):
    f = managed
    switch_on(f)
    image = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}]
    assert send_managed(f, messages=image).status_code == 200
    assert "(Request couldn't be read)" in held(f)[0]["what"]


def test_hr_07_its_own_switch(managed):
    f = managed
    f.stores.audit.set_option("settings", True)
    f.stores.audit.set_option("model_answers", True)
    assert entry(f).status_code == 200
    assert selected(f).status_code == 200
    assert AuditRecord.objects.filter(kind=KIND).count() == 0
    f.stores.audit.set_option("settings", False)
    f.stores.audit.set_option("model_answers", False)
    switch_on(f)
    assert entry(f).status_code == 200
    assert selected(f).status_code == 200
    # Newest first: the held record, then the earlier request's model answer.
    assert [row["kind"] for row in f.stores.audit.records()["records"]] == [
        KIND, "model_answers"
    ]
    assert f.stores.audit.options() == {
        "settings": False, KIND: True, "model_answers": False
    }
    f.stores.audit.set_option(KIND, False)
    assert entry(f).status_code == 200
    assert len(held(f)) == 1


def test_hr_08_records_and_logs_hold_no_request_text_or_secrets(managed, caplog):
    f = managed
    switch_on(f)
    f.stores.audit.set_option("model_answers", True)
    with caplog.at_level(logging.DEBUG):
        assert entry(f).status_code == 200
        assert selected(f).status_code == 200
        f.stores.classes.set_detection({"enabled": True, "class_id": "public"})
        assert entry(f).status_code == 403
    rows = list(AuditRecord.objects.values())
    assert len(rows) == 3
    text = json.dumps(rows, default=str) + caplog.text
    for secret in (
        PROMPT, EMAIL, "amara", "4711", "invoice", f.token, f.key, f.fp,
        "callback-test-password",
    ):
        assert secret not in text


@pytest.mark.parametrize("fault", ["record", "switch"])
def test_hr_09_a_failed_write_never_changes_the_hold(managed, caplog, fault):
    f = managed
    switch_on(f)
    target = (
        patch.object(
            AuditRecord.objects, "create", side_effect=OperationalError("audit down")
        )
        if fault == "record"
        else patch(
            "audit.services.AuditOption.objects.filter",
            side_effect=OperationalError("audit down"),
        )
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER), target:
        allowed = entry(f)
        f.stores.classes.set_detection({"enabled": True, "class_id": "public"})
        refused = entry(f)
    # The approved model stays allowed; the unapproved one stays refused.
    assert allowed.status_code == 200
    assert refused.status_code == 403
    assert "nothing was sent" in refused.json()["error"]
    assert AuditRecord.objects.filter(kind=KIND).count() == 0
    logged = [r for r in caplog.records if r.name == LOGGER]
    assert len(logged) == 2
    assert all(r.levelno == logging.WARNING for r in logged)
    assert "not written; the hold still applies" in logged[0].getMessage()
    for secret in (PROMPT, EMAIL, f.token, f.key, "audit down"):
        assert secret not in caplog.text
    assert entry(f).status_code == 403
    assert len(held(f)) == 1


def test_hr_10_customer_run_records_at_the_route_check_only(customer_run):
    f = customer_run
    switch_on(f)
    # Route check, then the final check on each attempt.
    assert shared(f).status_code == 200
    for _ in range(3):
        assert shared(f, final=True).status_code == 200
    [row] = held(f)
    assert re.fullmatch(ALLOWED, row["what"])
    # A held request refused at the route is recorded there.
    assert shared(f, model="public").status_code == 403
    assert "model public isn't approved for it, nothing was sent" in held(f)[0]["what"]
    # A refused model ID Keeplane doesn't know is not copied into the record.
    assert shared(f, model=EMAIL).status_code == 403
    assert held(f)[0]["what"].endswith(
        "a model Keeplane doesn't know isn't approved for it, nothing was sent"
    )
    assert EMAIL not in json.dumps(held(f))
    assert len(held(f)) == 3


def test_hr_11_a_managed_install_ignores_the_shared_route_check(managed):
    f = managed
    switch_on(f)
    # A managed install records on its installed entry check, never on the
    # shared one, so one request is never recorded twice.
    assert shared(f).status_code == 200
    assert AuditRecord.objects.filter(kind=KIND).count() == 0


def test_hr_12_each_record_names_only_its_developer(customer_run):
    f = customer_run
    switch_on(f)
    other = f.stores.identity.create_user(
        {"username": "second-developer", "role": "developer", "password": "x" * 24}
    )
    other_token = f.stores.identity.login("second-developer", "x" * 24)
    assert shared(f).status_code == 200
    # A project ID cannot borrow another developer's name.
    assert shared(f, token=other_token).status_code == 200
    rows = list(reversed(held(f)))
    assert [row["who"] for row in rows] == ["callback-developer", "second-developer"]
    assert all("project Callback" in row["what"] for row in rows)
    stored = list(
        AuditRecord.objects.filter(kind=KIND).order_by("pk").values_list(
            "actor_id", flat=True
        )
    )
    assert stored == [f.actor["id"], other["id"]]
    services = f.stores
    with (
        patch("common.api.IDENTITY", services.identity),
        patch("audit.views.AUDIT", services.audit),
    ):
        developer = Client()
        developer.cookies["keeplane_session"] = other_token
        denied = developer.get("/api/audit/records?kind=held_requests")
        assert denied.status_code == 403
        assert b"held back" not in denied.content
        anonymous = Client().get("/api/audit/records?kind=held_requests")
        assert anonymous.status_code in (401, 403)
        assert b"held back" not in anonymous.content


class Sequence(FakeInspector):
    """The entry check gets the first verdict, later checks the next ones."""

    def __init__(self, verdicts):
        super().__init__()
        self.verdicts = list(verdicts)

    def check(self, text):
        return self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]


@pytest.mark.parametrize("reason", [UNAVAILABLE, SLOW, FAILED])
def test_hr_13_held_only_at_the_final_check_is_recorded(managed, monkeypatch, reason):
    f = managed
    switch_on(f)
    clean = Verdict(False, "clean")
    f.fake = Sequence([clean, Verdict(True, reason)])
    monkeypatch.setattr(runtime_callback, "inspector", lambda: f.fake)
    assert entry(f, "Refactor the parser").status_code == 200
    assert held(f) == []
    assert selected(f, "Refactor the parser").status_code == 200
    [row] = held(f)
    why = held_request_records.REASONS[reason]
    assert f"held back as Confidential ({why}); project Callback; approved model private" in row["what"]
    # Refused at the final check: recorded too, and still refused.
    f.stores.classes.set_detection({"enabled": True, "class_id": "public"})
    f.fake = Sequence([Verdict(True, reason)])
    response = selected(f, "Refactor the parser")
    assert response.status_code == 403
    assert "isn't approved for it, nothing was sent" in held(f)[0]["what"]


def test_hr_14_the_final_check_never_repeats_a_steady_reason(managed):
    f = managed
    switch_on(f)
    # Personal data and unreadable text give the same answer at both checks,
    # so only the entry check records them, however often the final one runs.
    assert entry(f).status_code == 200
    for _ in range(3):
        assert selected(f).status_code == 200
    f.fake.verdict = Verdict(True, NOT_SENT)
    assert entry(f).status_code == 200
    assert selected(f).status_code == 200
    assert len(held(f)) == 2
    # During an outage each final attempt records: a duplicate, never a gap.
    f.fake.verdict = Verdict(True, UNAVAILABLE)
    assert entry(f).status_code == 200
    assert selected(f).status_code == 200
    assert selected(f).status_code == 200
    assert len(held(f)) == 5


def test_hr_15_customer_run_final_check_records_outage_holds(customer_run):
    f = customer_run
    switch_on(f)
    f.fake.verdict = Verdict(True, FOUND)
    assert shared(f, final=True).status_code == 200
    assert held(f) == []
    f.fake.verdict = Verdict(True, SLOW)
    assert shared(f, final=True).status_code == 200
    assert "(Detection took longer than 200 ms)" in held(f)[0]["what"]


def test_description_holds_only_the_given_details():
    assert held_request_records.description(
        "HR-0123456789ab", "Confidential", FOUND, "payments-api", "gpt-4.1", True
    ) == (
        "Request HR-0123456789ab held back as Confidential (Personal data detected); "
        "project payments-api; approved model gpt-4.1"
    )
    assert held_request_records.description(
        "HR-0123456789ab", "Public", SLOW, "payments-api", None, False
    ).endswith("a model Keeplane doesn't know isn't approved for it, nothing was sent")
    assert re.fullmatch(r"HR-[0-9a-f]{12}", held_request_records.reference())
