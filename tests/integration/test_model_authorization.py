"""Fresh sessions and explicit project policy precede current model eligibility."""

from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.utils import timezone

from accounts.models import User
from common.errors import StorageUnavailable
from data_classes.models import ProjectClass
from model_registry.authorization import DjangoModelAuthorization, ModelAccessDenied
from model_registry.fingerprints import fingerprint
from model_registry.policy import DjangoModelPolicy, ModelPolicyUnavailable
from projects.models import Project, ProjectUse
from projects.services import DjangoProjectStore


@pytest.fixture
def runtime(domain_services):
    stores, password = domain_services, "runtime-test-password"
    actor = stores.identity.create_user(
        {
            "username": "runtime-developer",
            "password": password,
            "role": "developer",
        }
    )
    token = stores.identity.login(actor["username"], password)
    project_id = str(uuid.uuid4())
    DjangoProjectStore().register_use(actor["id"], project_id, "Runtime project")
    stores.classes.set_enabled(True)
    ProjectClass.objects.create(project_id=project_id, data_class_id="confidential")
    resources = [{"id": name, "revision": 1} for name in ("private", "public")]
    for name, classes in (("private", ["Confidential"]), ("public", ["Public"])):
        stores.catalog.approve(name, classes, fingerprint(name, resources))
    state = SimpleNamespace(status=200, access=True, access_calls=[], gateway_calls=[])

    def models():
        state.gateway_calls.append(True)
        return state.status, {"data": [{"id": row["id"]} for row in resources]}

    def access(actor_id, context):
        state.access_calls.append((actor_id, context))
        return state.access

    policy = DjangoModelPolicy(
        SimpleNamespace(
            models=models,
            resources=lambda: (state.status, {"resources": resources}),
        )
    )
    service = DjangoModelAuthorization(stores.identity, policy, project_access=access)
    return SimpleNamespace(
        service=service,
        token=token,
        actor=actor,
        project=project_id,
        state=state,
        stores=stores,
        policy=policy,
    )


def test_authorized_result_contains_only_canonical_metadata(runtime):
    result = runtime.service.authorize(
        runtime.token, uuid.UUID(runtime.project).hex, "private"
    )
    assert result == {
        "actor_id": runtime.actor["id"],
        "project_id": runtime.project,
        "model_id": "private",
    }
    assert runtime.state.access_calls == [(runtime.actor["id"], runtime.project)]
    assert ProjectUse.objects.count() == 1


@pytest.mark.parametrize(
    "credential",
    [
        "missing",
        "invalid",
        "expired",
        "revoked",
        "disabled",
        "deleted",
        "password-changed",
    ],
)
def test_invalid_or_withdrawn_identity_stops_before_project_policy(runtime, credential):
    token = runtime.token
    user = User.objects.get(pk=runtime.actor["id"])
    if credential == "missing":
        token = None
    elif credential == "invalid":
        token = "invalid-session"
    elif credential == "expired":
        Session.objects.filter(pk=token).update(
            expire_date=timezone.now() - timedelta(seconds=1)
        )
    elif credential == "revoked":
        runtime.stores.identity.logout(token)
    elif credential == "disabled":
        user.is_active = False
        user.save(update_fields=["is_active"])
    elif credential == "deleted":
        runtime.stores.identity.delete_user(user.pk)
    else:
        user.set_password("replacement-runtime-password")
        user.save(update_fields=["password"])
    with pytest.raises(ModelAccessDenied) as error:
        runtime.service.authorize(token, runtime.project, "private")
    assert error.value.status == 401
    assert not runtime.state.access_calls and not runtime.state.gateway_calls


@pytest.mark.parametrize("project", [None, "not-a-uuid", str(uuid.uuid4())])
def test_unknown_context_does_not_register_or_query_gateway(runtime, project):
    with pytest.raises(ModelAccessDenied) as error:
        runtime.service.authorize(runtime.token, project, "private")
    assert error.value.status == 403
    assert Project.objects.count() == 1
    assert not runtime.state.access_calls and not runtime.state.gateway_calls


@pytest.mark.parametrize("access", [False, None, 1, "allow"])
def test_usage_and_ambiguous_access_answers_grant_nothing(runtime, access):
    runtime.state.access = access
    assert ProjectUse.objects.filter(user_id=runtime.actor["id"]).exists()
    with pytest.raises(ModelAccessDenied) as error:
        runtime.service.authorize(runtime.token, runtime.project, "private")
    assert error.value.status == 403
    assert not runtime.state.gateway_calls


def test_project_policy_is_required(runtime):
    with pytest.raises(TypeError):
        DjangoModelAuthorization(runtime.stores.identity, runtime.policy)
    with pytest.raises(ModelPolicyUnavailable):
        DjangoModelAuthorization(
            runtime.stores.identity, runtime.policy, project_access=None
        )


def test_admin_has_no_model_bypass_and_withdrawal_is_rechecked(runtime):
    User.objects.filter(pk=runtime.actor["id"]).update(role="admin")
    with pytest.raises(ModelAccessDenied):
        runtime.service.authorize(runtime.token, runtime.project, "public")
    runtime.service.authorize(runtime.token, runtime.project, "private")
    runtime.stores.catalog.remove("private")
    with pytest.raises(ModelAccessDenied):
        runtime.service.authorize(runtime.token, runtime.project, "private")


def test_gateway_and_project_storage_failure_produce_no_decision(runtime, monkeypatch):
    runtime.state.status = 503
    with pytest.raises(ModelPolicyUnavailable):
        runtime.service.authorize(runtime.token, runtime.project, "private")

    def fail(*args, **kwargs):
        raise DatabaseError("Unavailable project storage")

    monkeypatch.setattr(Project.objects, "filter", fail)
    with pytest.raises(StorageUnavailable):
        runtime.service.authorize(runtime.token, runtime.project, "private")


def test_access_and_session_withdrawal_are_rechecked_after_success(runtime):
    runtime.service.authorize(runtime.token, runtime.project, "private")
    runtime.state.access = False
    with pytest.raises(ModelAccessDenied):
        runtime.service.authorize(runtime.token, runtime.project, "private")
    runtime.state.access = True
    runtime.stores.identity.logout(runtime.token)
    with pytest.raises(ModelAccessDenied) as error:
        runtime.service.authorize(runtime.token, runtime.project, "private")
    assert error.value.status == 401
    assert len(runtime.state.gateway_calls) == 1


def test_unavailable_access_policy_stops_before_gateway(runtime):
    def unavailable(*args):
        raise ModelPolicyUnavailable("Project policy is unavailable")

    runtime.service.project_access = unavailable
    with pytest.raises(ModelPolicyUnavailable):
        runtime.service.authorize(runtime.token, runtime.project, "private")
    assert not runtime.state.gateway_calls
