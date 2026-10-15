"""Readiness follows known schema state; it never runs migrations."""

import json

import pytest
from django.db import OperationalError, connection
from django.db.migrations.recorder import MigrationRecorder
from django.test import RequestFactory

from common import readiness, web


pytestmark = pytest.mark.django_db


def probe():
    return web.readiness(RequestFactory().get("/health/ready"))


def test_current_schema_needs_one_read_query(django_assert_num_queries):
    with django_assert_num_queries(1):
        assert probe().status_code == 200


def test_pending_known_migration_refuses_readiness_without_writing():
    app, name = next(iter(readiness.known_migrations()[0]))
    MigrationRecorder.Migration.objects.filter(app=app, name=name).delete()
    before = list(MigrationRecorder.Migration.objects.values())
    assert probe().status_code == 503
    assert list(MigrationRecorder.Migration.objects.values()) == before
    assert web.app_health(RequestFactory().get("/health/app")).status_code == 200


def test_newer_unknown_migrations_do_not_drain_an_old_worker():
    MigrationRecorder.Migration.objects.create(app="accounts", name="9999_future")
    assert probe().status_code == 200


def test_database_outage_is_sanitized_and_next_probe_recovers(monkeypatch):
    original = MigrationRecorder.Migration.objects.using
    attempts = []

    def query(alias):
        attempts.append(alias)
        if len(attempts) == 1:
            raise OperationalError("password=sensitive-database-value")
        return original(alias)

    monkeypatch.setattr(MigrationRecorder.Migration.objects, "using", query)
    response = probe()
    assert response.status_code == 503
    assert json.loads(response.content) == {"app": "unavailable"}
    assert probe().status_code == 200


@pytest.mark.parametrize("applied", ["originals", "squash"])
def test_squashed_migration_alternatives_are_accepted(monkeypatch, applied):
    originals = (("fixture", "0001"), ("fixture", "0002"))
    squash = ("fixture", "0001_squashed")
    monkeypatch.setattr(readiness, "known_migrations", lambda: (
        frozenset((*originals, squash)), {squash: originals}))
    for app, name in originals if applied == "originals" else (squash,):
        MigrationRecorder.Migration.objects.create(app=app, name=name)
    assert readiness.schema_ready(connection)
