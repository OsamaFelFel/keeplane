"""Spec 005 ST18 and ST19 "Set a class" through the admin HTTP API.

Cases: tests/integration/data-class-admin-cases.md. Real Django storage and
sign-in; the gateway's list of set-up models is replaced by a fixed set.
"""

from unittest.mock import patch

import pytest
from data_classes import services as class_services
from django.test import Client
from projects.models import Project

SET_UP = {"coder", "reviewer"}
STARTERS = ["Public", "Internal", "Confidential"]


@pytest.fixture
def admin(domain_services):
    services = domain_services
    for model_id in sorted(SET_UP):
        services.catalog.approve(model_id, [], f"{model_id}-definition")
    client = Client()
    with (
        patch("common.api.IDENTITY", services.identity),
        patch("projects.views.AUDIT", services.audit),
        patch("data_classes.views.DATA_CLASSES", services.classes),
        patch("data_classes.views.effective_model_ids", lambda: (200, {}, SET_UP)),
        patch.object(class_services, "detection_available", lambda: True),
    ):
        client.cookies["keeplane_session"] = services.identity.login(
            "first-admin", "first-test-password-123"
        )

        def call(method, path, body=None, status=200):
            response = getattr(client, method)(
                path,
                body or {},
                content_type="application/json",
                HTTP_X_KEEPLANE_ACTION="1",
            )
            assert response.status_code == status, response.content
            return response.json()

        yield call, services


def classes(call):
    return {row["name"]: row for row in call("get", "/api/data-classes")["classes"]}


def test_dca_01_a_new_install_has_classes_off_and_nothing_asks_for_one(admin):
    call, services = admin
    project = Project.objects.create(name="Fresh")
    assert call("get", "/api/data-classes") == {"enabled": False, "classes": []}
    row = call("get", "/api/projects")["projects"][0]
    assert "data_class" not in row
    assert call("get", f"/api/projects/{project.pk}/class") == {
        "id": str(project.pk),
        "name": "Fresh",
        "classes_enabled": False,
    }
    # Nothing can be given a class until an admin turns classes on.
    call("post", "/api/data-classes", {"name": "Early", "approved_model_ids": []}, 409)
    call("put", f"/api/projects/{project.pk}/class", {"class_id": "public"}, 409)
    assert all(
        services.catalog.get(model_id)["approved_classes"] == [] for model_id in SET_UP
    )


def test_dca_02_turning_classes_on_lists_the_starters_once(admin):
    call, services = admin
    call("put", "/api/data-classes/mode", {"enabled": True})
    listing = call("get", "/api/data-classes")
    assert [row["name"] for row in listing["classes"]] == STARTERS
    assert all(row["approved_model_ids"] == [] for row in listing["classes"])
    # Spec 005 ST20 "Off by default": detection stays off until an admin turns it on.
    assert listing["detection"] == {
        "enabled": False,
        "class_id": "confidential",
        "available": True,
    }
    call("put", "/api/data-classes/mode", {"enabled": False})
    call("put", "/api/data-classes/mode", {"enabled": True})
    again = call("get", "/api/data-classes")["classes"]
    assert [row["name"] for row in again] == STARTERS
    assert [row["id"] for row in again] == [row["id"] for row in listing["classes"]]


def test_dca_03_an_added_class_is_listed_with_its_approved_models(admin):
    call, services = admin
    call("put", "/api/data-classes/mode", {"enabled": True})
    added = call(
        "post",
        "/api/data-classes",
        {"name": "Restricted", "approved_model_ids": ["coder"]},
        201,
    )
    row = classes(call)["Restricted"]
    assert row == {
        "id": added["id"],
        "name": "Restricted",
        "approved_model_ids": ["coder"],
        "project_count": 0,
    }
    assert list(classes(call)) == STARTERS + ["Restricted"]
    assert services.catalog.get("coder")["approved_classes"] == ["Restricted"]
    assert services.catalog.get("reviewer")["approved_classes"] == []


def test_dca_04_a_renamed_class_and_its_new_models_are_shown(admin):
    call, services = admin
    call("put", "/api/data-classes/mode", {"enabled": True})
    added = call(
        "post",
        "/api/data-classes",
        {"name": "Restricted", "approved_model_ids": ["coder"]},
        201,
    )
    call(
        "put",
        f"/api/data-classes/{added['id']}",
        {"name": "Secret", "approved_model_ids": ["reviewer"]},
    )
    shown = classes(call)
    assert "Restricted" not in shown
    assert shown["Secret"]["id"] == added["id"]
    assert shown["Secret"]["approved_model_ids"] == ["reviewer"]
    assert services.catalog.get("coder")["approved_classes"] == []
    assert services.catalog.get("reviewer")["approved_classes"] == ["Secret"]


def test_dca_05_a_class_a_project_uses_is_kept_and_the_refusal_says_why(admin):
    call, _ = admin
    call("put", "/api/data-classes/mode", {"enabled": True})
    added = call(
        "post",
        "/api/data-classes",
        {"name": "Restricted", "approved_model_ids": ["coder"]},
        201,
    )
    project = Project.objects.create(name="Uses it")
    call("put", f"/api/projects/{project.pk}/class", {"class_id": added["id"]})
    refused = call("delete", f"/api/data-classes/{added['id']}", status=409)
    assert refused == {"error": "Projects still use this class"}
    kept = classes(call)["Restricted"]
    assert kept["project_count"] == 1 and kept["approved_model_ids"] == ["coder"]
    call("put", f"/api/projects/{project.pk}/class", {"class_id": None})
    call("delete", f"/api/data-classes/{added['id']}")
    assert "Restricted" not in classes(call)


def test_dca_06_projects_shows_the_class_an_admin_set(admin):
    call, _ = admin
    call("put", "/api/data-classes/mode", {"enabled": True})
    project = Project.objects.create(name="Payments")
    Project.objects.create(name="Other")
    saved = call(
        "put", f"/api/projects/{project.pk}/class", {"class_id": "confidential"}
    )
    assert saved["data_class"] == {"id": "confidential", "name": "Confidential"}
    rows = {row["name"]: row for row in call("get", "/api/projects")["projects"]}
    assert rows["Payments"]["data_class"] == {
        "id": "confidential",
        "name": "Confidential",
    }
    assert rows["Other"]["data_class"] is None
    assert call("get", f"/api/projects/{project.pk}/class")["data_class"] == {
        "id": "confidential",
        "name": "Confidential",
    }
