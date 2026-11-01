""""Model answers" Audit records: one per request sent to a model.

Spec 006 ST21 and the owner decision in governance issue #36 ("'Sent' is
enough"). The plain-English cases are in model-answer-record-cases.md.
"""

import json
import logging
from functools import partial
import uuid
from unittest.mock import patch

import pytest
from audit.models import AuditRecord
from django.db import OperationalError, transaction
from django.test import Client
from model_registry import model_answer_records
from model_registry.provider_keys import managed_key_digest
from projects.services import DjangoProjectStore

from tests.integration import test_audit_persistence as persistence
from tests.integration.test_installed_runtime import send

pytest_plugins = ("tests.integration.test_installed_runtime",)

# Reuse the separate-process SQLite and PostgreSQL harness.
database = persistence.database
start_process = persistence.start_process

KIND = "model_answers"
LOGGER = "model_registry.model_answer_records"
PROMPT = "Summarise customer 4711's unpaid invoices"


SHARED = "/internal/runtime/authorize"


@pytest.fixture
def customer_run(callback, monkeypatch):
    """A customer-run (`existing`) gateway that calls only the shared check."""
    monkeypatch.setenv("GATEWAY_MODE", "existing")
    return callback


def send_shared(f, selected=False, body=None, **headers):
    return f.client.post(
        SHARED + ("/selected" if selected else ""),
        data=json.dumps(body or {"project_id": f.project, "model_id": "private"}),
        content_type="application/json",
        **{
            "HTTP_AUTHORIZATION": "Bearer " + f.token,
            "HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL": f.key,
            **headers,
        },
    )


def model_answers(f):
    return f.stores.audit.records(kind=KIND, page_size=50)["records"]


def switch_on(f):
    f.stores.audit.set_option(KIND, True)


def test_ma_01_after_install_nothing_is_recorded(installed):
    assert installed.stores.audit.options()[KIND] is False
    assert send(installed).status_code == 200
    assert send(installed, True).status_code == 200
    assert AuditRecord.objects.filter(kind=KIND).count() == 0


def test_ma_02_each_request_sent_writes_one_record_with_four_fields(installed):
    f = installed
    switch_on(f)
    for _ in range(3):
        assert send(f).status_code == 200
        assert send(f, True).status_code == 200
    rows = model_answers(f)
    # The entry check is not the send: only the final check writes a record.
    assert len(rows) == 3
    for row in rows:
        assert row["kind"] == KIND
        assert row["who"] == "callback-developer"
        assert row["what"] == "Request sent to model private; project Callback"
        assert row["when"].endswith("+00:00")
    stored = AuditRecord.objects.filter(kind=KIND).first()
    assert stored.actor_id == f.actor["id"]
    # Show and search find them like any other kind.
    audit = f.stores.audit
    assert audit.records(kind="all")["total"] == 3
    assert audit.records(kind="settings")["total"] == 0
    assert audit.records(kind=KIND, search="callback")["total"] == 3
    assert audit.records(kind=KIND, search="model private")["total"] == 3
    assert audit.records(kind=KIND, search="Callback-Developer")["total"] == 3
    assert audit.records(kind=KIND, search="other project")["total"] == 0


def test_ma_03_the_switch_works_on_its_own(installed):
    f = installed
    f.stores.audit.set_option("settings", True)
    f.stores.audit.set_option("held_requests", True)
    assert send(f, True).status_code == 200
    assert AuditRecord.objects.count() == 0
    switch_on(f)
    f.stores.audit.set_option("settings", False)
    f.stores.audit.set_option("held_requests", False)
    assert send(f, True).status_code == 200
    assert [row["kind"] for row in f.stores.audit.records()["records"]] == [KIND]
    f.stores.audit.set_option(KIND, False)
    assert send(f, True).status_code == 200
    # Turning it off stops new records; the earlier one stays.
    assert len(model_answers(f)) == 1


@pytest.mark.parametrize(
    "refusal",
    [
        "uninstalled-model",
        "old-definition",
        "unknown-project",
        "signed-out",
        "gateway-credential",
        "prompt-in-body",
        "class-changed",
    ],
)
def test_ma_04_a_refused_request_writes_nothing(installed, refusal):
    f = installed
    switch_on(f)
    changes, headers = {}, {}
    if refusal == "uninstalled-model":
        changes["model_id"] = "public"
    elif refusal == "old-definition":
        changes["definition_fingerprint"] = "0" * 64
    elif refusal == "unknown-project":
        changes["project_id"] = str(uuid.uuid4())
    elif refusal == "signed-out":
        f.stores.identity.logout(f.token)
    elif refusal == "gateway-credential":
        headers["HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL"] = "x" * 32
    elif refusal == "prompt-in-body":
        changes["prompt"] = PROMPT
    else:
        from data_classes.models import ProjectClass

        ProjectClass.objects.filter(project_id=f.project).update(
            data_class_id="public"
        )
    if headers:
        body = {
            "project_id": f.project,
            "model_id": "private",
            "definition_fingerprint": f.fp,
        }
        response = f.client.post(
            "/internal/runtime/installed/selected",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + f.token,
            **headers,
        )
    else:
        response = send(f, True, **changes)
    assert response.status_code in (400, 401, 403, 503)
    assert AuditRecord.objects.filter(kind=KIND).count() == 0


@pytest.mark.parametrize("fault", ["record", "switch"])
def test_ma_05_a_failed_record_write_still_allows_the_request(
    installed, caplog, fault
):
    f = installed
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
        response = send(f, True)
    assert response.status_code == 200
    assert response.json() == {
        "actor_id": f.actor["id"],
        "project_id": f.project,
        "model_id": "private",
    }
    assert AuditRecord.objects.filter(kind=KIND).count() == 0
    logged = [r for r in caplog.records if r.name == LOGGER]
    assert len(logged) == 1
    assert logged[0].levelno == logging.WARNING
    assert "not written; the request was allowed" in logged[0].getMessage()
    for secret in (f.token, f.key, f.fp, "audit down"):
        assert secret not in caplog.text
    # The next request records again once storage is back.
    assert send(f, True).status_code == 200
    assert len(model_answers(f)) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["managed", "customer-run"])
def test_ma_17_a_request_that_later_fails_keeps_its_record(
    installed, monkeypatch, mode
):
    f = installed
    switch_on(f)
    if mode == "customer-run":
        monkeypatch.setenv("GATEWAY_MODE", "existing")
        final = partial(send_shared, f, True)
    else:
        final = partial(send, f, True)
    assert final().status_code == 200
    # The final check is Keeplane's last step: its record is already committed
    # when it answers, before the gateway calls the model. Nothing waits for,
    # or is told about, the model's reply.
    assert not transaction.get_connection().in_atomic_block
    assert [row["what"] for row in model_answers(f)] == [
        "Request sent to model private; project Callback"
    ]
    # The model then fails and the developer's retry is refused because they
    # signed out: the first request keeps its record and the retry adds none.
    f.stores.identity.logout(f.token)
    assert final().status_code == 401
    rows = model_answers(f)
    assert len(rows) == 1 and rows[0]["who"] == "callback-developer"


def test_ma_06_records_hold_no_request_text_or_credentials(installed):
    f = installed
    switch_on(f)
    path = f.key_directory / ("key-" + "a" * 32)
    path.write_text("synthetic-managed-provider-key")
    f.resources[0]["value"]["auth"] = {"key": {"value": {"file": str(path)}}}
    f.fp = f.enroll(
        "shared", path.name, managed_key_digest(str(f.key_directory), str(path))
    )
    # The prompt never reaches Keeplane's check; a header carrying one is ignored.
    body = {
        "project_id": f.project,
        "model_id": "private",
        "definition_fingerprint": f.fp,
    }
    response = f.client.post(
        "/internal/runtime/installed/selected",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + f.token,
        HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=f.key,
        HTTP_X_KEEPLANE_PROMPT=PROMPT,
    )
    assert response.status_code == 200
    rows = list(AuditRecord.objects.filter(kind=KIND).values())
    assert len(rows) == 1
    text = json.dumps(rows, default=str)
    for secret in (
        PROMPT,
        f.token,
        f.key,
        f.fp,
        "synthetic-managed-provider-key",
        path.name,
        "callback-test-password",
    ):
        assert secret not in text


def test_ma_07_each_record_names_only_the_developer_who_sent_it(installed):
    f = installed
    switch_on(f)
    other = f.stores.identity.create_user(
        {"username": "second-developer", "role": "developer", "password": "x" * 24}
    )
    other_token = f.stores.identity.login("second-developer", "x" * 24)
    other_project = str(uuid.uuid4())
    DjangoProjectStore().register_use(other["id"], other_project, "Second")
    from data_classes.models import ProjectClass

    ProjectClass.objects.create(
        project_id=other_project, data_class_id="confidential"
    )
    first_token = f.token
    assert send(f, True).status_code == 200
    f.token = other_token
    assert send(f, True, project_id=other_project).status_code == 200
    # A project ID cannot borrow another developer's name: the actor comes from
    # the session, not from the request.
    assert send(f, True, project_id=f.project).status_code == 200
    f.token = first_token
    rows = list(reversed(model_answers(f)))
    assert [(row["who"], row["what"]) for row in rows] == [
        ("callback-developer", "Request sent to model private; project Callback"),
        ("second-developer", "Request sent to model private; project Second"),
        ("second-developer", "Request sent to model private; project Callback"),
    ]
    stored = list(
        AuditRecord.objects.filter(kind=KIND).order_by("pk").values_list(
            "actor_id", flat=True
        )
    )
    assert stored == [f.actor["id"], other["id"], other["id"]]


def test_ma_08_only_admins_can_read_the_records(installed):
    f = installed
    switch_on(f)
    assert send(f, True).status_code == 200
    services = f.stores
    with (
        patch("common.api.IDENTITY", services.identity),
        patch("audit.views.AUDIT", services.audit),
    ):
        developer = Client()
        developer.cookies["keeplane_session"] = services.identity.login(
            "callback-developer", "callback-test-password"
        )
        denied = developer.get("/api/audit/records?kind=model_answers")
        assert denied.status_code == 403
        assert b"Request sent" not in denied.content
        anonymous = Client().get("/api/audit/records?kind=model_answers")
        assert anonymous.status_code in (401, 403)
        assert b"Request sent" not in anonymous.content
        admin = Client()
        admin.cookies["keeplane_session"] = services.identity.login(
            "first-admin", "first-test-password-123"
        )
        shown = admin.get("/api/audit/records?kind=model_answers").json()
    assert [(row["who"], row["what"]) for row in shown["records"]] == [
        ("callback-developer", "Request sent to model private; project Callback")
    ]


def test_ma_09_the_shared_entry_check_writes_nothing(customer_run):
    f = customer_run
    switch_on(f)
    # The gateway may call the shared check at the route and again per backend.
    for _ in range(3):
        assert send_shared(f).status_code == 200
    assert AuditRecord.objects.filter(kind=KIND).count() == 0


def test_ma_10_records_persist_and_are_shared_across_processes(start_process):
    app = start_process()
    app.ask("migrate")
    result = app.ask("model_answers")
    assert result == {
        "off": False,
        "on": True,
        "failed_write": False,
        "missing_project": False,
        "logged": 2,
    }
    rows = start_process().records(kind=KIND)["records"]
    assert [(row["kind"], row["who"], row["what"]) for row in rows] == [
        (KIND, "process-developer", "Request sent to model alpha; project payments-api")
    ]
    assert rows[0]["when"].endswith("+00:00")


def test_description_uses_the_stored_names():
    assert (
        model_answer_records.description("gpt-4.1", "payments-api")
        == "Request sent to model gpt-4.1; project payments-api"
    )


# Customer-run gateways: the shared check's final variant writes the record.


def test_ma_11_a_customer_run_gateway_records_each_request_sent(customer_run):
    f = customer_run
    # Off after install: the shared final check writes nothing.
    assert send_shared(f).status_code == 200
    assert send_shared(f, True).status_code == 200
    assert AuditRecord.objects.filter(kind=KIND).count() == 0
    switch_on(f)
    for _ in range(3):
        # Entry check at the route, then the final check on the model backend.
        assert send_shared(f).status_code == 200
        response = send_shared(f, True)
        assert response.status_code == 200
        assert response.json() == {
            "actor_id": f.actor["id"],
            "project_id": f.project,
            "model_id": "private",
        }
    rows = model_answers(f)
    assert len(rows) == 3
    for row in rows:
        assert row["who"] == "callback-developer"
        assert row["what"] == "Request sent to model private; project Callback"
        assert row["when"].endswith("+00:00")
    assert f.stores.audit.records(kind="settings")["total"] == 0
    f.stores.audit.set_option(KIND, False)
    assert send_shared(f, True).status_code == 200
    assert len(model_answers(f)) == 3


@pytest.mark.parametrize(
    "refusal",
    [
        "model-not-set-up",
        "class-not-allowed",
        "unknown-project",
        "signed-out",
        "gateway-credential",
        "prompt-in-body",
        "class-changed",
    ],
)
def test_ma_12_a_request_the_shared_check_refuses_writes_nothing(
    customer_run, refusal
):
    f = customer_run
    switch_on(f)
    body, headers = {"project_id": f.project, "model_id": "private"}, {}
    if refusal == "model-not-set-up":
        body["model_id"] = "outside"
    elif refusal == "class-not-allowed":
        body["model_id"] = "public"
    elif refusal == "unknown-project":
        body["project_id"] = str(uuid.uuid4())
    elif refusal == "signed-out":
        f.stores.identity.logout(f.token)
    elif refusal == "gateway-credential":
        headers["HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL"] = "x" * 32
    elif refusal == "prompt-in-body":
        body["prompt"] = PROMPT
    else:
        from data_classes.models import ProjectClass

        ProjectClass.objects.filter(project_id=f.project).update(
            data_class_id="public"
        )
    response = send_shared(f, True, body, **headers)
    assert response.status_code in (400, 401, 403, 503)
    assert AuditRecord.objects.filter(kind=KIND).count() == 0


@pytest.mark.parametrize("fault", ["record", "switch"])
def test_ma_13_a_failed_write_on_the_shared_check_still_allows_the_request(
    customer_run, caplog, fault
):
    f = customer_run
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
        response = send_shared(f, True)
    assert response.status_code == 200
    assert response.json()["model_id"] == "private"
    assert AuditRecord.objects.filter(kind=KIND).count() == 0
    logged = [r for r in caplog.records if r.name == LOGGER]
    assert len(logged) == 1
    assert "not written; the request was allowed" in logged[0].getMessage()
    for secret in (f.token, f.key, "audit down"):
        assert secret not in caplog.text
    assert send_shared(f, True).status_code == 200
    assert len(model_answers(f)) == 1


def test_ma_14_shared_check_records_hold_no_request_text_or_credentials(
    customer_run,
):
    f = customer_run
    switch_on(f)
    response = send_shared(
        f, True, HTTP_X_KEEPLANE_PROMPT=PROMPT, HTTP_X_KEEPLANE_PROJECT_ID=f.project
    )
    assert response.status_code == 200
    rows = list(AuditRecord.objects.filter(kind=KIND).values())
    assert len(rows) == 1
    text = json.dumps(rows, default=str)
    for secret in (PROMPT, f.token, f.key, str(f.key_file), "callback-test-password"):
        assert secret not in text


def test_ma_15_shared_check_records_name_only_the_sending_developer(customer_run):
    f = customer_run
    switch_on(f)
    other = f.stores.identity.create_user(
        {"username": "second-developer", "role": "developer", "password": "x" * 24}
    )
    other_token = f.stores.identity.login("second-developer", "x" * 24)
    other_project = str(uuid.uuid4())
    DjangoProjectStore().register_use(other["id"], other_project, "Second")
    from data_classes.models import ProjectClass

    ProjectClass.objects.create(
        project_id=other_project, data_class_id="confidential"
    )
    first_token = f.token
    assert send_shared(f, True).status_code == 200
    f.token = other_token
    assert (
        send_shared(
            f, True, {"project_id": other_project, "model_id": "private"}
        ).status_code
        == 200
    )
    f.token = first_token
    rows = list(reversed(model_answers(f)))
    assert [(row["who"], row["what"]) for row in rows] == [
        ("callback-developer", "Request sent to model private; project Callback"),
        ("second-developer", "Request sent to model private; project Second"),
    ]
    stored = list(
        AuditRecord.objects.filter(kind=KIND).order_by("pk").values_list(
            "actor_id", flat=True
        )
    )
    assert stored == [f.actor["id"], other["id"]]


def test_ma_16_one_recorder_per_gateway_mode(installed, monkeypatch):
    f = installed
    switch_on(f)
    # Managed: the installed final check records; the shared final check
    # refuses, so one request can never be recorded twice.
    assert send(f).status_code == 200
    assert send(f, True).status_code == 200
    refused = send_shared(f, True)
    assert refused.status_code == 503
    assert refused.json() == {
        "error": "Managed gateways use the installed runtime checks"
    }
    assert len(model_answers(f)) == 1
    # Customer-run: the installed checks refuse and the shared one records.
    monkeypatch.setenv("GATEWAY_MODE", "existing")
    assert send(f, True).status_code == 503
    assert send_shared(f).status_code == 200
    assert send_shared(f, True).status_code == 200
    assert len(model_answers(f)) == 2
