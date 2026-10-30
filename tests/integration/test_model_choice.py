"""A missing own key moves a task to another allowed model, never past policy."""

import hashlib

import pytest
from accounts.cli_credentials import RuntimeIdentity
from accounts.models import User
from model_registry import model_choice, runtime_views
from model_registry.fingerprints import fingerprint
from model_registry.models import DeveloperProviderKey, ModelApproval
from model_registry.policy import DjangoModelPolicy
from projects.access import organization_project_access

from tests.integration.test_installed_personal_runtime import KEY
from tests.integration.test_installed_runtime import send as entry

pytest_plugins = ("tests.integration.test_installed_personal_runtime",)
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def choice(personal, monkeypatch):
    f = personal
    monkeypatch.setattr(model_choice, "IDENTITY", f.stores.identity)
    monkeypatch.setattr(model_choice, "MODEL_GATEWAY", f.gateway)
    monkeypatch.setattr(
        runtime_views, "model_policy", lambda: DjangoModelPolicy(f.gateway)
    )

    def install(name, key_choice="none", classes=("Confidential",)):
        fp = fingerprint(name, f.resources)
        f.stores.catalog.approve(name, list(classes), fp, key_choice=key_choice)
        f.declaration["models"][name] = {
            "fingerprint": fp,
            "key_choice": key_choice,
            "key_name": "",
            "key_digest": "",
        }
        f.write()

    f.install = install
    return f


def ask(f, model="private", token=None, query=None):
    return f.client.get(
        f"/api/runtime/projects/{f.project}/model-choice",
        {"model_id": model} if query is None else query,
        HTTP_AUTHORIZATION="Bearer " + (token or f.token),
    )


def chosen(f, model_id, reason, requested="private"):
    return {
        "project_id": f.project,
        "requested_model_id": requested,
        "model_id": model_id,
        "reason": reason,
    }


def test_usable_own_key_keeps_the_requested_model(choice):
    choice.install("public")
    response = ask(choice)
    assert response.status_code == 200
    assert response.json() == chosen(choice, "private", None)
    assert "no-store" in response["Cache-Control"]
    assert not choice.reads


def test_missing_key_moves_to_another_allowed_model_that_the_gateway_admits(choice):
    choice.install("public")
    choice.store.remove("private")
    assert ask(choice).json() == chosen(choice, "public", "missing")
    # The gateway still checks the chosen model, and the original model keeps
    # its existing missing-key refusal.
    assert entry(choice, model_id="public").status_code == 200
    assert entry(choice).json() == {"error": "Add or replace your provider key"}
    assert not choice.reads


def test_removed_key_moves_the_next_task_and_a_new_key_moves_it_back(choice):
    choice.install("public")
    assert ask(choice).json()["model_id"] == "private"
    choice.store.remove("private")
    assert ask(choice).json() == chosen(choice, "public", "missing")
    choice.store.put("private", KEY)
    assert ask(choice).json() == chosen(choice, "private", None)


@pytest.mark.parametrize("state", ["refused", "outdated"])
def test_keys_the_resolver_would_not_use_also_move_the_task(choice, state):
    choice.install("public")
    row = DeveloperProviderKey.objects.get(owner_id=choice.actor["id"])
    if state == "refused":
        row.refused = True
    else:
        row.validation_fingerprint = "a" * 64
    row.save()
    assert ask(choice).json() == chosen(choice, "public", state)
    assert entry(choice).status_code == 403


def test_another_owners_key_does_not_count(choice):
    choice.install("public")
    choice.store.remove("private")
    other = User.objects.get(username="first-admin")
    DeveloperProviderKey.objects.create(
        owner=other,
        model_id="private",
        key_name="key-" + "b" * 32,
        validation_fingerprint=choice.fp,
    )
    assert ask(choice).json() == chosen(choice, "public", "missing")


def test_no_other_allowed_model_fails_clearly(choice):
    choice.store.remove("private")
    response = ask(choice)
    assert response.status_code == 200
    assert response.json() == chosen(choice, None, "missing")


@pytest.mark.parametrize(
    "candidate",
    ["other-class", "not-installed", "gateway-only", "own-key-missing", "shared-key-gone"],
)
def test_fallback_never_bypasses_setup_installation_key_or_class(choice, candidate):
    f = choice
    f.store.remove("private")
    if candidate == "other-class":
        f.install("public", classes=("Public",))
    elif candidate == "not-installed":
        f.stores.catalog.approve(
            "public", ["Confidential"], fingerprint("public", f.resources)
        )
    elif candidate == "gateway-only":
        # "outside" is listed by the gateway but has no Keeplane setup.
        f.declaration["models"]["outside"] = {
            "fingerprint": fingerprint("outside", f.resources),
            "key_choice": "none",
            "key_name": "",
            "key_digest": "",
        }
        f.write()
    elif candidate == "own-key-missing":
        f.install("public", key_choice="personal")
    else:
        path = f.key_directory / ("key-" + "c" * 32)
        path.write_text("synthetic-managed-provider-key")
        path.chmod(0o600)
        public = next(r for r in f.resources if r["id"] == "public")
        public["value"]["auth"] = {"key": {"value": {"file": str(path)}}}
        f.install("public", key_choice="shared")
        f.declaration["models"]["public"].update(
            key_name=path.name,
            key_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        f.write()
        assert ask(f).json()["model_id"] == "public"
        path.unlink()
    assert ask(f).json() == chosen(f, None, "missing")


def test_candidates_are_tried_in_model_id_order(choice):
    choice.install("public")
    choice.install("outside")
    choice.store.remove("private")
    assert ask(choice).json() == chosen(choice, "outside", "missing")
    ModelApproval.objects.filter(pk="outside").update(approved_classes=["Public"])
    assert ask(choice).json() == chosen(choice, "public", "missing")


def test_a_removed_model_is_never_chosen_and_gets_no_work(choice):
    # Spec 004 ST23: after removal, a model added outside Keeplane stays in the
    # gateway, but it is gateway-only again and must get no work.
    choice.install("public")
    choice.install("outside")
    choice.store.remove("private")
    assert ask(choice).json() == chosen(choice, "outside", "missing")
    choice.stores.catalog.remove("outside")
    assert ask(choice).json() == chosen(choice, "public", "missing")
    # Its stale enrollment no longer matches any setup, so the gateway entry
    # check fails closed before any provider contact.
    assert entry(choice, model_id="outside").status_code in (403, 503)
    choice.stores.catalog.remove("public")
    assert ask(choice).json() == chosen(choice, None, "missing")


def chooser(f):
    return model_choice.DjangoModelChoice(
        RuntimeIdentity(f.stores.identity),
        DjangoModelPolicy(f.gateway),
        f.gateway,
        str(f.key_directory),
        project_access=organization_project_access,
        managed=True,
        manifest_file=str(f.manifest_file),
    )


def test_next_allowed_skips_every_model_already_tried(choice):
    # The shared fallback filter: a later fallback passes all models it tried.
    choice.install("public")
    choice.install("outside")
    actor = choice.actor["id"]
    pick = chooser(choice).next_allowed
    assert pick(choice.token, actor, choice.project, skip={"private"}) == "outside"
    assert pick(choice.token, actor, choice.project, skip={"private", "outside"}) == "public"
    assert pick(choice.token, actor, choice.project, skip={"private", "outside", "public"}) is None
    # The developer's own usable key makes the requested model a candidate too.
    assert pick(choice.token, actor, choice.project, skip=set()) == "outside"
    choice.store.remove("private")
    assert pick(choice.token, actor, choice.project, skip={"outside", "public"}) is None


def test_requested_model_without_own_key_is_unchanged(choice):
    choice.install("public")
    assert ask(choice, "public").json() == chosen(choice, "public", None, "public")


def test_response_contains_no_key_material(choice):
    choice.install("public")
    choice.store.remove("private")
    choice.store.put("private", KEY)
    row = DeveloperProviderKey.objects.get(owner_id=choice.actor["id"])
    row.refused = True
    row.save()
    body = ask(choice).content.decode()
    for secret in (KEY, row.key_name, choice.fp, choice.token, str(choice.key_directory)):
        assert secret not in body


@pytest.mark.parametrize(
    "query,status",
    [
        ({}, 400),
        ({"model_id": "private", "owner_id": "forged"}, 400),
        ({"model_id": ""}, 400),
        ({"model_id": "outside"}, 403),
    ],
)
def test_invalid_or_unallowed_requests_are_refused(choice, query, status):
    assert ask(choice, query=query).status_code == status


def test_signed_out_or_unknown_project_is_refused(choice):
    assert ask(choice, token="invalid").status_code == 401
    choice.project = "not-a-project"
    assert ask(choice).status_code == 403


def test_policy_outage_returns_no_choice(choice):
    choice.install("public")
    choice.store.remove("private")
    choice.state.status = 503
    response = ask(choice)
    assert response.status_code == 503
    assert response.json() == {"error": "Model choice is unavailable"}


def test_existing_gateway_mode_uses_its_own_gate_for_candidates(choice, monkeypatch):
    monkeypatch.setenv("GATEWAY_MODE", "existing")
    choice.store.remove("private")
    choice.stores.catalog.approve(
        "public", ["Confidential"], fingerprint("public", choice.resources)
    )
    assert ask(choice).json() == chosen(choice, "public", "missing")
    # That gate never admits Personal models, so one cannot be a fallback.
    ModelApproval.objects.filter(pk="public").update(key_choice="personal")
    assert ask(choice).json() == chosen(choice, None, "missing")
