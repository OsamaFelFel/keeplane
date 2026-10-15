"""First-use projects, identity checks and atomic usage records."""

from datetime import timedelta
from unittest.mock import patch
import uuid

from django.db import OperationalError
from django.utils import timezone
import pytest

from accounts.models import User
from common.errors import StorageUnavailable
from data_classes.models import ProjectClass
from projects.models import Project, ProjectUse
from projects.services import DjangoProjectStore, ProjectError


@pytest.fixture
def developer(db):
    return User.objects.create(username="project-developer", role="developer")


def test_first_use_without_onboarding_or_class(developer):
    project_id = uuid.uuid4()
    result = DjangoProjectStore().register_use(developer.pk, project_id, "Example")
    assert result == {"id": str(project_id), "name": "Example"}
    assert ProjectUse.objects.get(project_id=project_id).user_id == developer.pk
    assert not ProjectClass.objects.filter(project_id=str(project_id)).exists()


def test_repeat_keeps_identity_name_and_first_seen(developer):
    store, project_id = DjangoProjectStore(), uuid.uuid4()
    store.register_use(developer.pk, project_id, "Original")
    project = Project.objects.get(pk=project_id)
    usage = ProjectUse.objects.get(project=project)
    later = usage.last_seen_at + timedelta(minutes=1)
    with patch("projects.services.timezone.now", return_value=later):
        result = store.register_use(developer.pk, project_id.hex, "Changed by client")
    usage.refresh_from_db()
    project.refresh_from_db()
    assert result["name"] == "Original"
    assert usage.first_seen_at < usage.last_seen_at == later
    assert project.first_seen_at < project.last_seen_at == later
    assert Project.objects.count() == ProjectUse.objects.count() == 1


def test_two_accounts_share_one_project_without_replacing_usage(developer):
    other = User.objects.create(username="another-developer", role="developer")
    project_id = uuid.uuid4()
    for user in (developer, other):
        DjangoProjectStore().register_use(user.pk, project_id, "Shared")
    assert Project.objects.count() == 1
    assert set(ProjectUse.objects.values_list("user_id", flat=True)) == {
        developer.pk, other.pk
    }


def test_waiting_request_does_not_move_last_seen_before_first_use(developer):
    started = timezone.now()
    created = started + timedelta(seconds=1)
    project = Project.objects.create(
        name="Created by another request", first_seen_at=created, last_seen_at=created
    )
    after_lock = created + timedelta(seconds=1)
    with patch("projects.services.timezone.now", side_effect=[started, after_lock]):
        DjangoProjectStore().register_use(developer.pk, project.pk, "Example")
    project.refresh_from_db()
    assert project.first_seen_at == created
    assert project.last_seen_at == after_lock


@pytest.mark.parametrize("user_id", [None, "invalid", uuid.uuid4()])
def test_missing_or_unknown_account_creates_nothing(db, user_id):
    with pytest.raises(ProjectError) as error:
        DjangoProjectStore().register_use(user_id, uuid.uuid4(), "Example")
    assert error.value.status == 401
    assert not Project.objects.exists()


def test_disabled_account_is_rechecked(developer):
    developer.is_active = False
    developer.save(update_fields=["is_active"])
    with pytest.raises(ProjectError) as error:
        DjangoProjectStore().register_use(developer.pk, uuid.uuid4(), "Example")
    assert error.value.status == 401
    assert not Project.objects.exists()


@pytest.mark.parametrize("project_id,name", [
    ("not-an-id", "Example"), (uuid.uuid4(), " "), (uuid.uuid4(), "x" * 121),
    (uuid.uuid4(), "Line\nbreak"), (uuid.uuid4(), None),
])
def test_invalid_context_creates_nothing(developer, project_id, name):
    with pytest.raises(ProjectError) as error:
        DjangoProjectStore().register_use(developer.pk, project_id, name)
    assert error.value.status == 400
    assert not Project.objects.exists()


def test_usage_failure_rolls_back_first_registration(developer):
    with patch("projects.services.ProjectUse.objects.update_or_create",
               side_effect=OperationalError("unavailable")):
        with pytest.raises(StorageUnavailable):
            DjangoProjectStore().register_use(developer.pk, uuid.uuid4(), "Example")
    assert not Project.objects.exists()
    assert not ProjectUse.objects.exists()
