"""Projects are visible only to admins, with bounded pages and current class names."""

from unittest.mock import patch

import pytest
from accounts.models import User
from data_classes.models import DataClass, ProjectClass, Settings
from django.db import OperationalError
from django.test import Client
from projects.models import Project
from projects.services import DjangoProjectStore


@pytest.fixture
def project_client(domain_services):
    token = domain_services.identity.login("first-admin", "first-test-password-123")
    client = Client()
    client.cookies["keeplane_session"] = token
    with patch("common.api.IDENTITY", domain_services.identity):
        yield client


def test_admin_lists_first_use_users_without_private_account_fields(project_client):
    user = User.objects.create(
        username="project-user", password="never-expose", role="developer"
    )
    project = Project.objects.create(name="Example")
    DjangoProjectStore().register_use(user.pk, project.pk, project.name)
    response = project_client.get("/api/projects")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.json()["projects"] == [
        {
            "id": str(project.pk),
            "name": "Example",
            "initialized": False,
            "users": [{"id": str(user.pk), "username": user.username}],
        }
    ]
    assert "never-expose" not in response.content.decode()


def test_search_and_stable_pages(project_client):
    for name in ("Alpha", "alpha", "Beta"):
        Project.objects.create(name=name)
    first = project_client.get("/api/projects?search=ALPHA&page_size=1").json()
    second = project_client.get("/api/projects?search=ALPHA&page_size=1&page=2").json()
    assert first["total"] == second["total"] == 2
    assert first["has_more"] and not second["has_more"]
    assert first["projects"][0]["id"] != second["projects"][0]["id"]
    assert project_client.get("/api/projects?page=100").json()["projects"] == []


def test_class_fields_hidden_when_off_and_current_when_on(project_client):
    project = Project.objects.create(name="Classed")
    data_class = DataClass.objects.create(
        id="confidential", name="Confidential", position=0
    )
    ProjectClass.objects.create(project_id=str(project.pk), data_class=data_class)
    assert "data_class" not in project_client.get("/api/projects").json()["projects"][0]
    Settings.objects.update_or_create(pk=1, defaults={"classes_enabled": True})
    row = project_client.get("/api/projects").json()["projects"][0]
    assert row["data_class"] == {"id": "confidential", "name": "Confidential"}
    data_class.name = "Private"
    data_class.save()
    assert (
        project_client.get("/api/projects").json()["projects"][0]["data_class"]["name"]
        == "Private"
    )


@pytest.mark.parametrize(
    "query", ["page=0", "page=no", "page=10001", "page_size=51", "search=" + "x" * 121]
)
def test_invalid_query_is_rejected(project_client, query):
    assert project_client.get("/api/projects?" + query).status_code == 400


def test_anonymous_and_developer_cannot_read_project_usage(domain_services):
    client = Client()
    with patch("common.api.IDENTITY", domain_services.identity):
        assert client.get("/api/projects").status_code == 401
        domain_services.identity.create_user(
            {
                "username": "developer-one",
                "password": "developer-test-password",
                "role": "developer",
            }
        )
        token = domain_services.identity.login(
            "developer-one", "developer-test-password"
        )
        client.cookies["keeplane_session"] = token
        assert client.get("/api/projects").status_code == 403


def test_database_failure_is_a_sanitized_unavailable_response(project_client):
    with patch(
        "projects.listing.Project.objects.filter",
        side_effect=OperationalError("private-db-host"),
    ):
        response = project_client.get("/api/projects")
    assert response.status_code == 503
    assert "private-db-host" not in response.content.decode()
