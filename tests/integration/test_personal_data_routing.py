"""Personal-data detection on the gateway request checks (Spec 005 ST20).

Cases: tests/integration/personal-data-routing-cases.md. A deterministic fake
stands in for the language model; tests/integration/test_personal_data_model.py
checks the real one.
"""

import json
import secrets
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from accounts import authentication
from data_classes import services as class_services
from data_classes.contracts import CLASS_IN_USE, NOT_INSTALLED, DataClassError
from data_classes.models import ProjectClass, Settings
from django.test import Client, override_settings
from model_registry import runtime_callback
from model_registry.fingerprints import fingerprint
from model_registry.policy import DjangoModelPolicy
from personal_data.inspection import FOUND, NOT_SENT, SLOW, Verdict
from projects.services import DjangoProjectStore

EMAIL = "amara.okonkwo@example.com"  # invented, on a reserved domain


class FakeInspector:
    """Finds EMAIL in the text; can be told to act slow or record calls."""

    def __init__(self):
        self.texts, self.verdict = [], None

    def check(self, text):
        self.texts.append(text)
        if self.verdict is not None:
            return self.verdict
        if text is None:
            return Verdict(True, NOT_SENT)
        return Verdict(True, FOUND) if EMAIL in text else Verdict(False, "clean")


@pytest.fixture
def gate(domain_services, tmp_path, monkeypatch):
    stores, password = domain_services, "detection-test-password"
    actor = stores.identity.create_user(
        {"username": "detection-developer", "role": "developer", "password": password}
    )
    token = stores.identity.login(actor["username"], password)
    project = str(uuid.uuid4())
    DjangoProjectStore().register_use(actor["id"], project, "Detection")
    stores.classes.set_enabled(True)
    resources = [{"id": name, "revision": 1} for name in ("open", "private", "both")]
    for name, classes in (
        ("open", ["Public"]),
        ("private", ["Confidential"]),
        ("both", ["Public", "Confidential"]),
    ):
        stores.catalog.approve(name, classes, fingerprint(name, resources))
    gateway = SimpleNamespace(
        models=lambda: (200, {"data": [{"id": r["id"]} for r in resources]}),
        resources=lambda: (200, {"resources": resources}),
    )
    key, path = secrets.token_urlsafe(32), tmp_path / "gateway-key"
    path.write_text(key + "\n")
    path.chmod(0o600)
    fake = FakeInspector()
    monkeypatch.setattr(authentication, "IDENTITY", stores.identity)
    monkeypatch.setattr(runtime_callback, "IDENTITY", stores.identity)
    monkeypatch.setattr(runtime_callback, "model_policy", lambda: DjangoModelPolicy(gateway))
    monkeypatch.setattr(runtime_callback, "inspector", lambda: fake)
    monkeypatch.setattr(class_services, "detection_available", lambda: True)
    monkeypatch.setattr(runtime_callback, "record_sent_request", lambda result: None)
    held = []
    monkeypatch.setattr(
        runtime_callback, "held_request", lambda result, verdict: held.append(
            (result["held_class"], verdict.reason)
        )
    )
    with override_settings(ALLOWED_HOSTS=["testserver"], RUNTIME_AUTHORIZER_KEY_FILE=str(path)):
        yield SimpleNamespace(
            client=Client(enforce_csrf_checks=True), token=token, key=key,
            project=project, stores=stores, fake=fake, held=held,
        )


def ask(gate, model, text="Refactor the parser", path="/internal/runtime/authorize",
        messages=None, **extra):
    body = {"project_id": gate.project, "model_id": model, **extra}
    if messages is None and text is not None:
        messages = [{"role": "user", "content": text}]
    if messages is not None:
        body["messages"] = messages
    return gate.client.post(
        path,
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + gate.token,
        HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=gate.key,
    )


def detection(gate, enabled=True, class_id=None):
    body = {"enabled": enabled}
    if class_id:
        body["class_id"] = class_id
    return gate.stores.classes.set_detection(body)


# PR-01 Off by default: nothing is inspected and no route changes.
def test_pr_01_off_by_default_changes_no_route(gate):
    assert gate.stores.classes.detection() == {
        "enabled": False, "class_id": "confidential", "available": True
    }
    response = ask(gate, "open", f"mail {EMAIL}")
    assert response.status_code == 200
    assert gate.fake.texts == []


# PR-02 A request with personal data from a project with no class goes only to
# models approved for the detection class (Confidential by default).
def test_pr_02_detected_request_uses_only_the_detection_class(gate):
    detection(gate)
    denied = ask(gate, "open", f"mail {EMAIL}")
    assert denied.status_code == 403
    assert denied.json() == {
        "error": "This request is handled as Confidential and open isn't approved for it, "
        "so nothing was sent. Run it with a model approved for Confidential, or ask "
        "your admin to approve one."
    }
    for model in ("private", "both"):
        allowed = ask(gate, model, f"mail {EMAIL}")
        assert allowed.status_code == 200
        assert set(allowed.json()) == {"actor_id", "project_id", "model_id"}
    assert ask(gate, "open", "Refactor the parser").status_code == 200


# PR-03 Detection never relaxes a project restriction.
def test_pr_03_project_class_still_applies_to_held_requests(gate):
    detection(gate, class_id="public")
    ProjectClass.objects.create(project_id=gate.project, data_class_id="confidential")
    # "open" is approved for the detection class only, "private" for the project's only.
    assert ask(gate, "open", f"mail {EMAIL}").status_code == 403
    assert ask(gate, "private", f"mail {EMAIL}").status_code == 403
    assert ask(gate, "both", f"mail {EMAIL}").status_code == 200
    assert ask(gate, "open", "Refactor the parser").status_code == 403


# PR-04 Down, slow, failed or not sent: the request is handled as the class.
@pytest.mark.parametrize("verdict", [
    Verdict(True, SLOW), Verdict(True, "detector_unavailable"), Verdict(True, "detector_failed"),
])
def test_pr_04_detector_failure_holds_the_request(gate, verdict):
    detection(gate)
    gate.fake.verdict = verdict
    assert ask(gate, "open").status_code == 403
    assert ask(gate, "private").status_code == 200


def test_pr_04_a_check_without_messages_is_held(gate):
    detection(gate)
    assert ask(gate, "open", text=None).status_code == 403
    assert gate.fake.texts == [None]
    assert ask(gate, "private", text=None).status_code == 200


def test_pr_04_unreadable_parts_are_held(gate):
    detection(gate)
    image = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}]
    assert ask(gate, "open", messages=image).status_code == 403
    for odd in (
        [{"role": "assistant", "tool_calls": "call"}],
        [{"role": "assistant", "function_call": {"name": "f", "arguments": "{}"},
          "audio": {"id": "a"}}],
    ):
        assert ask(gate, "open", messages=odd).status_code == 403
        assert ask(gate, "private", messages=odd).status_code == 200


# PR-05 The admin's chosen class is the one held requests use.
def test_pr_05_choosing_another_class(gate):
    detection(gate, class_id="public")
    assert ask(gate, "open", f"mail {EMAIL}").status_code == 200
    assert ask(gate, "private", f"mail {EMAIL}").status_code == 403


# PR-06 Detection does nothing while data classes are off, and turning it on
# between the unlocked read and the policy read still holds the request.
def test_pr_06_classes_off_means_no_detection(gate):
    detection(gate)
    gate.stores.classes.set_enabled(False)
    assert ask(gate, "open", f"mail {EMAIL}").status_code == 200
    assert gate.fake.texts == []


def test_pr_06_turned_on_mid_check_holds(gate, monkeypatch):
    detection(gate)
    monkeypatch.setattr(DjangoModelPolicy, "detection_on", lambda self: False)
    assert ask(gate, "open", "Refactor the parser").status_code == 403
    assert gate.fake.texts == []


# PR-07 The final check also inspects, and marks the held request for Audit.
def test_pr_07_selected_check_inspects_and_reports_held(gate):
    detection(gate)
    path = "/internal/runtime/authorize/selected"
    with patch.dict("os.environ", {"GATEWAY_MODE": "existing"}):
        assert ask(gate, "open", f"mail {EMAIL}", path=path).status_code == 403
        assert ask(gate, "private", f"mail {EMAIL}", path=path).status_code == 200
        assert ask(gate, "private", "Refactor the parser", path=path).status_code == 200
    assert gate.held == [("Confidential", FOUND)]


# PR-08 Size limits: metadata alone keeps 4 KiB; messages may be larger; an
# install's gateway sends null messages for a body over 1 MiB, which is held.
def test_pr_08_size_limits(gate):
    detection(gate)
    long_text = "Refactor the parser. " * 2000
    assert ask(gate, "open", long_text).status_code == 200
    assert gate.fake.texts[-1] == long_text
    padded = ask(gate, "open", text=None, padding="x" * 5000)
    assert padded.status_code == 413
    over = gate.client.post(
        "/internal/runtime/authorize",
        data=json.dumps({"project_id": gate.project, "model_id": "open", "messages": None}),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + gate.token,
        HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=gate.key,
    )
    assert over.status_code == 403 and gate.fake.texts[-1] is None
    assert ask(gate, "private", "x" * (2 * 1024 * 1024)).status_code == 200
    # Only a gateway that ignores the 1 MiB guard can exceed the check limit.
    too_big = ask(gate, "private", "x" * (runtime_callback.MAX_CHECKED_BODY + 1))
    assert too_big.status_code == 413


def test_pr_08_extra_fields_are_still_refused(gate):
    response = ask(gate, "open", padding="x")
    assert response.status_code == 400


# PR-09 Request text never appears in responses.
def test_pr_09_no_request_text_in_responses(gate):
    detection(gate)
    for model in ("open", "private"):
        response = ask(gate, model, f"mail {EMAIL}")
        assert EMAIL not in response.content.decode()


# PR-10 Admin settings: default class, class rules, Audit wording.
def test_pr_10_detection_settings(gate):
    classes = gate.stores.classes
    with pytest.raises(DataClassError) as error:
        classes.set_detection({"enabled": "yes"})
    assert error.value.status == 400
    with pytest.raises(DataClassError):
        classes.set_detection({"enabled": True, "class_id": "missing"})
    with pytest.raises(DataClassError):
        classes.set_detection({"enabled": True, "extra": 1})
    assert classes.set_detection({"enabled": True}) == {
        "enabled": True, "class_id": "confidential"
    }
    with pytest.raises(DataClassError) as error:
        classes.remove("confidential")
    assert (error.value.status, error.value.message) == (409, CLASS_IN_USE)
    classes.set_detection({"enabled": False, "class_id": "internal"})
    with pytest.raises(DataClassError) as error:
        classes.remove("internal")
    assert error.value.message == CLASS_IN_USE
    assert classes.detection()["class_id"] == "internal"
    classes.remove("confidential")
    classes.set_enabled(False)
    with pytest.raises(DataClassError) as error:
        classes.set_detection({"enabled": True})
    assert error.value.status == 409
    settings = Settings.objects.get(pk=1)
    assert settings.detection_enabled is False and settings.detection_class_id == "internal"


# PR-11 The Data classes API shows and changes detection; Audit names each change.
def test_pr_11_admin_api_and_audit_records(domain_services):
    services = domain_services
    client = Client()
    with (
        patch("common.api.IDENTITY", services.identity),
        patch("audit.views.AUDIT", services.audit),
        patch("data_classes.views.DATA_CLASSES", services.classes),
        patch("data_classes.views.effective_model_ids", lambda: (200, {}, set())),
        patch.object(class_services, "detection_available", lambda: True),
    ):
        client.cookies["keeplane_session"] = services.identity.login(
            "first-admin", "first-test-password-123"
        )

        def call(method, path, body=None, status=200):
            response = getattr(client, method)(
                path, body or {}, content_type="application/json",
                HTTP_X_KEEPLANE_ACTION="1",
            )
            assert response.status_code == status, response.content
            return response.json()

        assert call("put", "/api/data-classes/detection", {"enabled": True}, 409) == {
            "error": "Turn on data classes first"
        }
        call("put", "/api/audit/options/settings", {"enabled": True})
        call("put", "/api/data-classes/mode", {"enabled": True})
        assert call("get", "/api/data-classes")["detection"] == {
            "enabled": False, "class_id": "confidential", "available": True
        }
        call("put", "/api/data-classes/detection", {"enabled": True})
        call("put", "/api/data-classes/detection", {"enabled": True, "class_id": "internal"})
        call("put", "/api/data-classes/detection", {"enabled": False})
        assert call("get", "/api/data-classes")["detection"] == {
            "enabled": False, "class_id": "internal", "available": True
        }
        shown = client.get("/api/audit/records?kind=settings").json()
        refused = client.put(
            "/api/data-classes/detection", {"enabled": True},
            content_type="application/json",
        )
        assert refused.status_code == 403
    assert [row["what"] for row in reversed(shown["records"])][1:] == [
        "Turned personal-data detection on; detected requests handled as Confidential",
        "Changed the class for detected requests: Confidential to Internal",
        "Turned personal-data detection off",
    ]


# PR-12 Without the detector or an install that sends messages, the switch
# can't be turned on; if either disappears after it was on, requests are held.
def test_pr_12_not_installed(gate, monkeypatch):
    monkeypatch.setattr(class_services, "detection_available", lambda: False)
    assert gate.stores.classes.detection()["available"] is False
    with pytest.raises(DataClassError) as error:
        detection(gate)
    assert (error.value.status, error.value.message) == (409, NOT_INSTALLED)
    assert Settings.objects.get(pk=1).detection_enabled is False
    monkeypatch.setattr(class_services, "detection_available", lambda: True)
    detection(gate)
    monkeypatch.setattr(class_services, "detection_available", lambda: False)
    detection(gate, class_id="internal")  # still on: the class can change
    assert detection(gate, enabled=False)["enabled"] is False
    detection_on = Settings.objects.filter(pk=1)
    detection_on.update(detection_enabled=True)
    assert ask(gate, "open", text=None).status_code == 403


# PR-13 Detection off and a check without messages: the decision and the
# 4 KiB metadata limit are exactly as before detection existed.
def test_pr_13_off_without_messages_is_unchanged(gate):
    for model in ("open", "private", "both"):
        response = ask(gate, model, text=None)
        assert response.status_code == 200
        assert set(response.json()) == {"actor_id", "project_id", "model_id"}
    assert ask(gate, "open", text=None, padding="x" * 5000).status_code == 413
    assert gate.fake.texts == []
    # Every other route keeps the 64 KiB request limit.
    other = gate.client.post(
        "/api/data-classes", data="x" * (64 * 1024 + 1), content_type="application/json"
    )
    assert other.status_code == 413
