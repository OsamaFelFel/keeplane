"""Clones of one remote are one project on the real server (Spec 009 ST30, D149).

Cases: tests/integration/cli-repo-project-cases.md (RPJ-01 to RPJ-03). Two
developers' CLIs reach the real Django runtime routes over HTTP from their own
clones, with no project ID or name given.
"""

import os
import shutil
import subprocess
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest
from accounts import authentication
from common import api
from data_classes.models import ProjectClass
from django.core.wsgi import get_wsgi_application
from django.test import Client, override_settings
from model_registry import runtime_views
from model_registry.fingerprints import fingerprint
from model_registry.policy import DjangoModelPolicy

from components.cli import project_identity
from components.cli.project_registration import register
from components.cli.server_connection import models

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        shutil.which("git") is None, reason="Git builds the sample clones"
    ),
]


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def clone(path, remote):
    environment = dict(
        os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull
    )
    for arguments in (
        ["init", "-q", str(path)],
        ["-C", str(path), "remote", "add", "origin", remote],
    ):
        subprocess.run(
            ["git", *arguments], check=True, env=environment, capture_output=True
        )
    return Path(path)


@pytest.fixture
def server(domain_services, monkeypatch):
    stores = domain_services
    developers = {}
    for username in ("repo-developer-a", "repo-developer-b"):
        password = username + "-password"
        actor = stores.identity.create_user(
            {"username": username, "role": "developer", "password": password}
        )
        developers[username] = (actor, stores.identity.login(username, password))
    stores.classes.set_enabled(True)  # Classes on, and no class set on the repo yet.
    resources = [{"id": name, "revision": 1} for name in ("coder", "reviewer")]
    stores.catalog.approve("coder", ["Public"], fingerprint("coder", resources))
    stores.catalog.approve(
        "reviewer", ["Confidential"], fingerprint("reviewer", resources)
    )
    gateway = SimpleNamespace(
        models=lambda: (200, {"data": [{"id": r["id"]} for r in resources]}),
        resources=lambda: (200, {"resources": resources}),
    )
    monkeypatch.setattr(authentication, "IDENTITY", stores.identity)
    monkeypatch.setattr(api, "IDENTITY", stores.identity)
    monkeypatch.setattr(
        runtime_views, "model_policy", lambda: DjangoModelPolicy(gateway)
    )
    http = make_server(
        "127.0.0.1", 0, get_wsgi_application(), handler_class=QuietHandler
    )
    address = f"http://127.0.0.1:{http.server_port}"
    monkeypatch.setattr(api, "PUBLIC_ORIGIN", address)
    thread = Thread(target=http.serve_forever, daemon=True)
    try:
        with override_settings(
            PUBLIC_ORIGIN=address, ALLOWED_HOSTS=["127.0.0.1", "testserver"]
        ):
            thread.start()
            admin = Client()
            admin.cookies["keeplane_session"] = stores.identity.login(
                "first-admin", "first-test-password-123"
            )
            yield SimpleNamespace(
                address=address, developers=developers, admin=admin, stores=stores
            )
    finally:
        if thread.is_alive():
            http.shutdown()
        http.server_close()
        thread.join(timeout=5)


def test_rpj_01_two_developers_clones_of_one_remote_are_one_not_set_up_project(
    server, tmp_path
):
    clones = {
        "repo-developer-a": clone(
            tmp_path / "a" / "payments-api",
            "git@example.test:platform/payments-api.git",
        ),
        "repo-developer-b": clone(
            tmp_path / "b" / "checkout", "https://b@Example.test/Platform/payments-api"
        ),
    }
    projects = {}
    for username, path in clones.items():
        project = project_identity.identify(path)
        _, token = server.developers[username]
        registered = register(server.address, project.id, project.name, token)
        projects[username] = (project, registered)
    first, second = (row[0] for row in projects.values())
    assert first.id == second.id
    # The server keeps the first name it was given.
    assert {row[1]["name"] for row in projects.values()} == {"platform/payments-api"}
    listing = server.admin.get("/api/projects").json()["projects"]
    assert len(listing) == 1
    row = listing[0]
    assert row["id"] == first.id and row["name"] == "platform/payments-api"
    assert row["initialized"] is False
    assert sorted(user["username"] for user in row["users"]) == [
        "repo-developer-a",
        "repo-developer-b",
    ]


def test_rpj_02_until_an_admin_sets_its_class_the_repo_can_use_every_model(
    server, tmp_path
):
    path = clone(tmp_path / "sample", "https://example.test/platform/sample.git")
    project = project_identity.identify(path)
    _, token = server.developers["repo-developer-a"]
    register(server.address, project.id, project.name, token)
    every = [{"id": "coder"}, {"id": "reviewer"}]
    assert models(server.address, project.id, token)["models"] == every
    ProjectClass.objects.create(project_id=project.id, data_class_id="confidential")
    assert models(server.address, project.id, token)["models"] == [{"id": "reviewer"}]


def test_rpj_03_a_repo_with_no_remote_is_its_own_project_under_its_folder_name(
    server, tmp_path
):
    subprocess.run(
        ["git", "init", "-q", str(tmp_path / "scratch")],
        check=True,
        env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull),
    )
    project = project_identity.identify(tmp_path / "scratch")
    _, token = server.developers["repo-developer-a"]
    assert (
        register(server.address, project.id, project.name, token)["name"] == "scratch"
    )
    row = server.admin.get("/api/projects").json()["projects"][0]
    assert row["name"] == "scratch" and str(tmp_path) not in row["name"]
    assert project_identity.identify(tmp_path / "scratch").id == row["id"]
