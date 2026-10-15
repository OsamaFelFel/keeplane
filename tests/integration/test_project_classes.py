"""Project class writes retain policy invariants and share the settings Audit transaction."""

import uuid
from unittest.mock import patch

import pytest
from common.errors import StorageUnavailable
from data_classes.contracts import DataClassError
from data_classes.models import ProjectClass
from django.db import OperationalError
from django.test import Client
from projects.classification import DjangoProjectClasses
from projects.models import Project
from projects.services import ProjectError


@pytest.fixture
def context(domain_services):
    domain_services.classes.set_enabled(True)
    return (
        domain_services,
        Project.objects.create(name="Example"),
        ("admin-id", "Admin"),
    )


def test_assign_clear_and_class_in_use_guard(context):
    service, project, actor = context
    writer = DjangoProjectClasses(service.audit)
    assert (
        writer.assign(project.pk, "confidential", actor)["data_class"]["name"]
        == "Confidential"
    )
    with pytest.raises(DataClassError) as error:
        service.classes.remove("confidential")
    assert error.value.status == 409
    assert writer.assign(project.pk, None, actor)["data_class"] is None
    assert not ProjectClass.objects.filter(project_id=str(project.pk)).exists()
    service.classes.remove("confidential")


def test_audit_records_changes_once_and_off_means_no_record(context):
    service, project, actor = context
    writer = DjangoProjectClasses(service.audit)
    writer.assign(project.pk, "public", actor)
    assert service.audit.records()["total"] == 0
    service.audit.set_option("settings", True)
    writer.assign(project.pk, "confidential", actor)
    writer.assign(project.pk, "confidential", actor)
    records = service.audit.records(kind="settings")["records"]
    assert len(records) == 1
    assert records[0]["who"] == "Admin"
    assert str(project.pk) in records[0]["what"]
    assert "Public" in records[0]["what"] and "Confidential" in records[0]["what"]


def test_audit_failure_rolls_back_class_change(context):
    service, project, actor = context
    writer = DjangoProjectClasses(service.audit)
    writer.assign(project.pk, "public", actor)
    with (
        patch.object(
            service.audit,
            "record_in_transaction",
            side_effect=OperationalError("database down"),
        ),
        pytest.raises(StorageUnavailable),
    ):
        writer.assign(project.pk, "confidential", actor)
    assert (
        ProjectClass.objects.get(project_id=str(project.pk)).data_class_id == "public"
    )


def test_browser_class_write_rejects_missing_csrf_token(context):
    service, project, _ = context
    client = Client(enforce_csrf_checks=True)
    client.cookies["keeplane_session"] = service.identity.login(
        "first-admin", "first-test-password-123"
    )
    with patch("common.api.IDENTITY", service.identity):
        response = client.put(
            f"/api/projects/{project.pk}/class",
            {"class_id": "public"},
            content_type="application/json",
            HTTP_X_KEEPLANE_ACTION="1",
        )
    assert response.status_code == 403
    assert not ProjectClass.objects.exists()


@pytest.mark.parametrize("class_id", ["unknown", "", [], True])
def test_invalid_class_keeps_assignment(context, class_id):
    service, project, actor = context
    with pytest.raises(ProjectError) as error:
        DjangoProjectClasses(service.audit).assign(project.pk, class_id, actor)
    assert error.value.status == 400
    assert not ProjectClass.objects.exists()


def test_unknown_project_and_disabled_mode_keep_state(context):
    service, project, actor = context
    writer = DjangoProjectClasses(service.audit)
    with pytest.raises(ProjectError) as error:
        writer.assign(uuid.uuid4(), "public", actor)
    assert error.value.status == 404
    writer.assign(project.pk, "confidential", actor)
    service.classes.set_enabled(False)
    with pytest.raises(ProjectError) as error:
        writer.assign(project.pk, None, actor)
    assert error.value.status == 409
    assert (
        ProjectClass.objects.get(project_id=str(project.pk)).data_class_id
        == "confidential"
    )


def test_class_write_requires_admin_action_and_explicit_choice(context):
    service, project, _ = context
    client = Client()
    path = f"/api/projects/{project.pk}/class"
    with (
        patch("common.api.IDENTITY", service.identity),
        patch("projects.views.AUDIT", service.audit),
    ):
        assert (
            client.put(
                path, {"class_id": "public"}, content_type="application/json"
            ).status_code
            == 401
        )
        client.cookies["keeplane_session"] = service.identity.login(
            "first-admin", "first-test-password-123"
        )
        assert (
            client.put(
                path, {"class_id": "public"}, content_type="application/json"
            ).status_code
            == 403
        )
        assert (
            client.put(
                path, {}, content_type="application/json", HTTP_X_KEEPLANE_ACTION="1"
            ).status_code
            == 400
        )
        response = client.put(
            path,
            {"class_id": "public"},
            content_type="application/json",
            HTTP_X_KEEPLANE_ACTION="1",
        )
        assert response.status_code == 200
        service.identity.create_user(
            {
                "username": "project-dev",
                "password": "developer-test-password",
                "role": "developer",
            }
        )
        client.cookies["keeplane_session"] = service.identity.login(
            "project-dev", "developer-test-password"
        )
        assert (
            client.put(
                path,
                {"class_id": None},
                content_type="application/json",
                HTTP_X_KEEPLANE_ACTION="1",
            ).status_code
            == 403
        )
    assert (
        ProjectClass.objects.get(project_id=str(project.pk)).data_class_id == "public"
    )
