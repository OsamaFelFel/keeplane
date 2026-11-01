"""Readiness checks schema and enabled sign-in prerequisites without writing."""

import builtins
import json

import pytest
from common import readiness, web
from django.db import OperationalError, connection
from django.db.migrations.recorder import MigrationRecorder
from django.test import RequestFactory

pytestmark = pytest.mark.django_db


def probe():
    return web.readiness(RequestFactory().get("/health/ready"))


def test_current_schema_needs_one_read_query(django_assert_num_queries):
    with django_assert_num_queries(1):
        assert probe().status_code == 200


def test_disabled_sign_in_never_reads_optional_clients(settings, monkeypatch):
    settings.CLI_OAUTH_ENABLED = False
    original = builtins.__import__

    def forbid_optional(name, *args, **kwargs):
        if name.startswith("oauth2_provider"):
            raise AssertionError("Disabled sign-in must not import optional models")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_optional)
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


# PD-13 in tests/unit/personal-data-detection-cases.md: an installed detector
# keeps the app out of service only while its first load runs.
class Loading:
    def __init__(self, starting):
        self.is_starting, self.asked = starting, 0

    def starting(self):
        self.asked += 1
        return self.is_starting

    def detector(self):
        self.asked += 1


@pytest.fixture
def detection(settings, monkeypatch):
    from personal_data import inspection

    def install(setting, available, starting=False):
        settings.PERSONAL_DATA_DETECTION_INSTALLED = setting
        fake = Loading(starting)
        monkeypatch.setattr(inspection, "detection_available", lambda: available)
        monkeypatch.setattr(inspection, "inspector", lambda: fake)
        return fake

    return install


def test_pd_13_readiness_is_unchanged_without_the_install_setting(detection):
    from personal_data.inspection import warm_up

    fake = detection(False, True, starting=True)
    assert probe().status_code == 200
    assert warm_up() is False and fake.asked == 0


def test_pd_13_readiness_waits_while_the_installed_detector_loads(detection):
    from personal_data.inspection import warm_up

    fake = detection(True, True, starting=True)
    assert warm_up() is True and fake.asked == 1
    response = probe()
    assert response.status_code == 503
    assert json.loads(response.content) == {"app": "starting"}
    fake.is_starting = False
    assert probe().status_code == 200


def test_pd_13_setting_on_without_the_detector_is_ready_and_logged(detection, caplog):
    from personal_data.inspection import warm_up

    fake = detection(True, False, starting=True)
    with caplog.at_level("WARNING", logger="personal_data.inspection"):
        assert warm_up() is False
    assert probe().status_code == 200 and fake.asked == 0
    assert "no personal-data detector" in caplog.text
    assert "postgres-detection" in caplog.text
