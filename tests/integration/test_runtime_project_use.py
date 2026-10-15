"""First-use HTTP registration derives its account from the bearer session."""

from types import SimpleNamespace
import uuid

import pytest
from django.db import OperationalError
from django.test import Client, override_settings

from accounts import authentication
from accounts.models import User
from data_classes.models import DataClass, ProjectClass, Settings
from projects.models import Project, ProjectUse


@pytest.fixture
def usage(domain_services, monkeypatch):
    identity, password = domain_services.identity, "project-use-test-password"
    actor = identity.create_user(
        {"username": "use-developer", "role": "developer", "password": password}
    )
    token = identity.login(actor["username"], password)
    monkeypatch.setattr(authentication, "IDENTITY", identity)
    with override_settings(ALLOWED_HOSTS=["testserver"]):
        yield SimpleNamespace(
            client=Client(enforce_csrf_checks=True),
            actor=actor,
            token=token,
            project=str(uuid.uuid4()),
            identity=identity,
        )


def send(usage, body, token=None):
    return usage.client.post(
        "/api/runtime/projects",
        data=body,
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + (token or usage.token),
    )


def test_first_use_creates_project_and_usage_without_class_or_onboarding(usage):
    response = send(
        usage, {"project_id": uuid.UUID(usage.project).hex, "name": " Example "}
    )
    assert response.status_code == 200
    assert response.json() == {"project_id": usage.project, "name": "Example"}
    assert "no-store" in response["Cache-Control"]
    assert usage.token not in response.content.decode()
    assert ProjectUse.objects.get(project_id=usage.project).user_id == uuid.UUID(
        usage.actor["id"]
    )
    assert not ProjectClass.objects.exists() and not Settings.objects.exists()


def test_repeat_preserves_name_class_and_other_users(usage):
    body = {"project_id": usage.project, "name": "Original"}
    assert send(usage, body).status_code == 200
    DataClass.objects.create(id="restricted", name="Restricted", position=0)
    ProjectClass.objects.create(project_id=usage.project, data_class_id="restricted")
    password = "another-project-password"
    other = usage.identity.create_user(
        {"username": "other-use", "role": "developer", "password": password}
    )
    token = usage.identity.login(other["username"], password)
    body["name"] = "Replacement"
    assert send(usage, body, token).json()["name"] == "Original"
    assert send(usage, body).json()["name"] == "Original"
    assert Project.objects.count() == 1 and ProjectUse.objects.count() == 2
    assert ProjectClass.objects.get(pk=usage.project).data_class_id == "restricted"


@pytest.mark.parametrize(
    "change",
    [
        {"user_id": "somebody-else"},
        {"data_class": "Public"},
        {"role": "admin"},
        {"access": True},
        {"project_id": "invalid"},
        {"name": " "},
        {"name": "x" * 121},
    ],
)
def test_claims_and_invalid_fields_cannot_create_state(usage, change):
    body = {"project_id": usage.project, "name": "Example", **change}
    assert send(usage, body).status_code == 400
    assert not Project.objects.exists() and not ProjectUse.objects.exists()


@pytest.mark.parametrize("body", [[], {}, {"name": "Example"}])
def test_incomplete_or_non_object_body_creates_nothing(usage, body):
    assert send(usage, body).status_code == 400
    assert not Project.objects.exists()


def test_cookie_only_and_withdrawn_session_cannot_register(usage):
    body = {"project_id": usage.project, "name": "Example"}
    usage.client.cookies["keeplane_session"] = usage.token
    response = usage.client.post(
        "/api/runtime/projects", data=body, content_type="application/json"
    )
    assert response.status_code == 401
    User.objects.filter(pk=usage.actor["id"]).update(is_active=False)
    assert send(usage, body).status_code == 401
    assert not Project.objects.exists()


def test_storage_failure_rolls_back_first_use_over_http(usage, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OperationalError("Unavailable usage storage")

    monkeypatch.setattr(ProjectUse.objects, "update_or_create", unavailable)
    assert (
        send(usage, {"project_id": usage.project, "name": "Example"}).status_code == 503
    )
    assert not Project.objects.exists() and not ProjectUse.objects.exists()
