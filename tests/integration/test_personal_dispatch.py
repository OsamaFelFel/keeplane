"""Actual account/project/class records and private files; synthetic gateway definitions."""

import json
import uuid
from types import SimpleNamespace

import pytest
from accounts.models import User
from common.errors import StorageUnavailable
from data_classes.models import ProjectClass
from model_registry import developer_keys
from model_registry.authorization import ModelAccessDenied
from model_registry.models import ModelApproval
from model_registry.personal_dispatch import DjangoPersonalDispatch
from model_registry.policy import DjangoModelPolicy
from projects.access import organization_project_access
from projects.services import DjangoProjectStore

from tests.integration import test_developer_key_resolution as key_cases

pytestmark = pytest.mark.django_db(transaction=True)
key_owner = key_cases.owned
KEY, NEXT = key_cases.KEY, key_cases.NEXT


@pytest.fixture
def dispatch(key_owner, domain_services, monkeypatch):
    owned = key_owner
    identity = domain_services.identity
    tokens = []
    for store in (owned.a, owned.b):
        owner = User.objects.get(pk=store.owner_id)
        owner.set_password("synthetic-dispatch-password")
        owner.save(update_fields=["password"])
        tokens.append(identity.login(owner.username, "synthetic-dispatch-password"))
    project = str(uuid.uuid4())
    DjangoProjectStore().register_use(owned.a.owner_id, project, "Dispatch project")
    domain_services.classes.set_enabled(True)
    ProjectClass.objects.create(project_id=project, data_class_id="confidential")
    ModelApproval.objects.update(approved_classes=["Confidential"])
    gateway = SimpleNamespace(
        models=lambda: (200, {"data": [{"id": "model"}]}),
        resources=lambda: (200, {"resources": [owned.resource]}),
        request=lambda *args, **kwargs: (200, {"resources": [owned.resource]}),
    )
    service = DjangoPersonalDispatch(
        identity,
        DjangoModelPolicy(gateway),
        gateway,
        str(owned.root),
        project_access=organization_project_access,
    )
    reads = []
    original = developer_keys.read_private_key

    def observed(*args):
        reads.append(True)
        return original(*args)

    monkeypatch.setattr(developer_keys, "read_private_key", observed)
    return SimpleNamespace(
        service=service,
        identity=identity,
        tokens=tokens,
        project=project,
        owned=owned,
        reads=reads,
    )


def resolve(dispatch, *, token=None, digest=None, project=None):
    return dispatch.service.resolve(
        token or dispatch.tokens[0],
        project or dispatch.project,
        "model",
        definition_fingerprint=digest or dispatch.owned.digest,
    )


def test_owner_selected_from_current_identity_and_result_redacts_key(dispatch):
    result = resolve(dispatch, project=uuid.UUID(dispatch.project).hex)
    assert result.actor_id == str(dispatch.owned.a.owner_id)
    assert result.project_id == dispatch.project and result.model_id == "model"
    assert result.definition_fingerprint == dispatch.owned.digest
    assert result.for_provider() == KEY
    assert KEY not in repr(result) and KEY not in str(result)
    with pytest.raises(TypeError):
        json.dumps(result)
    with pytest.raises(StorageUnavailable):
        resolve(dispatch, token=dispatch.tokens[1])
    assert len(dispatch.reads) == 1
    dispatch.owned.b.put("model", NEXT)
    assert resolve(dispatch, token=dispatch.tokens[1]).for_provider() == NEXT
    assert resolve(dispatch).for_provider() == KEY


def test_each_call_uses_replacement_then_denies_removed_key(dispatch):
    first = resolve(dispatch)
    dispatch.owned.a.put("model", NEXT)
    assert resolve(dispatch).for_provider() == NEXT
    dispatch.owned.a.remove("model")
    with pytest.raises(StorageUnavailable):
        resolve(dispatch)
    assert len(dispatch.reads) == 2
    assert first.for_provider() == KEY  # No promise to revoke returned memory.


@pytest.mark.parametrize("change", ["logout", "disabled", "class", "project", "choice"])
def test_current_authorization_denies_before_any_secret_read(dispatch, change):
    if change == "logout":
        dispatch.identity.logout(dispatch.tokens[0])
    elif change == "disabled":
        User.objects.filter(pk=dispatch.owned.a.owner_id).update(is_active=False)
    elif change == "class":
        ProjectClass.objects.update(data_class_id="public")
    elif change == "project":
        dispatch.service.authorization.project_access = lambda *args: False
    else:
        ModelApproval.objects.update(key_choice="shared")
    with pytest.raises((ModelAccessDenied, StorageUnavailable)):
        resolve(dispatch)
    assert not dispatch.reads


@pytest.mark.parametrize(
    "change", ["logout", "disabled", "class", "project", "registry", "remove"]
)
def test_withdrawal_after_initial_policy_check_precedes_secret_read(
    dispatch, monkeypatch, change
):
    original = dispatch.service.authorization.authorize
    calls = []

    def withdrawn(*args):
        result = original(*args)
        if not calls:
            calls.append(True)
            if change == "logout":
                dispatch.identity.logout(dispatch.tokens[0])
            elif change == "disabled":
                User.objects.filter(pk=dispatch.owned.a.owner_id).update(
                    is_active=False
                )
            elif change == "class":
                ProjectClass.objects.update(data_class_id="public")
            elif change == "project":
                dispatch.service.authorization.project_access = lambda *args: False
            elif change == "registry":
                dispatch.owned.resource["revision"] += 1
            else:
                dispatch.owned.a.remove("model")
        return result

    monkeypatch.setattr(dispatch.service.authorization, "authorize", withdrawn)
    with pytest.raises(StorageUnavailable, match="^Provider key is unavailable$"):
        resolve(dispatch)
    assert calls and not dispatch.reads


@pytest.mark.parametrize("digest", ["b" * 64, "A" * 64, "a" * 63, 42])
def test_captured_destination_fingerprint_must_match_current_binding(dispatch, digest):
    with pytest.raises(StorageUnavailable, match="^Provider key is unavailable$"):
        resolve(dispatch, digest=digest)
    assert not dispatch.reads


def test_current_policy_and_key_errors_hide_credential_details(dispatch, monkeypatch):
    def failed(*args):
        raise OSError(KEY + str(dispatch.owned.root))

    monkeypatch.setattr(developer_keys, "read_private_key", failed)
    with pytest.raises(StorageUnavailable) as error:
        resolve(dispatch)
    assert KEY not in str(error.value) and str(dispatch.owned.root) not in str(
        error.value
    )
