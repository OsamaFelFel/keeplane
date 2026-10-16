"""Installed handoff checks real policy and owned files before each key read."""

from urllib.parse import urlencode

import pytest
from accounts.models import User
from data_classes.models import ProjectClass
from model_registry import developer_keys, personal_transport
from model_registry.developer_keys import DjangoDeveloperKeyStore
from model_registry.key_validation import (
    DjangoProviderKeyValidator,
    VerifiedProviderKey,
)
from model_registry.policy import DjangoModelPolicy

from tests.integration.test_installed_runtime import send as decision

pytest_plugins = ("tests.integration.test_installed_runtime",)
pytestmark = pytest.mark.django_db(transaction=True)
PATH = "/internal/runtime/installed-provider-token"
KEY, NEXT = "synthetic-installed-owner-key", "synthetic-installed-next-key"


@pytest.fixture
def personal(installed, monkeypatch):
    f = installed
    f.fp = f.enroll("personal")
    current = DjangoProviderKeyValidator(f.gateway)

    class SyntheticVerification:
        def __call__(self, owner, model, key):
            # Real provider admission is covered separately; every file read
            # still uses the actual current-definition checker and owner lock.
            return VerifiedProviderKey(str(owner), model, f.fp)

        require_current = current.require_current

    monkeypatch.setattr("integrations.gateway.keys.os.fchown", lambda *args: None)
    f.store = DjangoDeveloperKeyStore(
        f.actor["id"], str(f.key_directory), validate_key=SyntheticVerification()
    )
    f.store.put("private", KEY)
    f.reads = []
    original = developer_keys.read_private_key

    def observed(*args):
        f.reads.append(True)
        return original(*args)

    monkeypatch.setattr(developer_keys, "read_private_key", observed)
    monkeypatch.setattr(personal_transport, "IDENTITY", f.stores.identity)
    monkeypatch.setattr(personal_transport, "MODEL_GATEWAY", f.gateway)
    monkeypatch.setattr(
        personal_transport, "model_policy", lambda: DjangoModelPolicy(f.gateway)
    )
    return f


def handoff(f, *, path=PATH, key=None, **changes):
    body = {
        "grant_type": personal_transport.EXCHANGE_TYPE,
        "subject_token_type": personal_transport.ACCESS_TYPE,
        "subject_token": f.token,
        "project_id": f.project,
        "model_id": "private",
        "definition_fingerprint": f.fp,
        **changes,
    }
    return f.client.post(
        path,
        data=urlencode(body),
        content_type="application/x-www-form-urlencoded",
        HTTP_X_KEEPLANE_GATEWAY_CREDENTIAL=f.key if key is None else key,
    )


def test_personal_entry_final_and_handoff_keep_the_raw_definition(personal):
    f = personal
    assert decision(f).status_code == decision(f, True).status_code == 200
    assert handoff(f).json()["access_token"] == KEY
    f.store.put("private", NEXT)
    assert handoff(f).json()["access_token"] == NEXT
    f.store.remove("private")
    assert handoff(f).status_code == 503
    assert len(f.reads) == 3 and not f.resources[0]["value"].get("auth")


def test_missing_owner_key_stops_at_entry_before_native_backend_handoff(personal):
    f = personal
    f.store.remove("private")
    entry = decision(f)
    assert entry.status_code == 503 and not f.reads
    # Selection stays metadata-only; the native entry gate must precede it.
    assert decision(f, True).status_code == 200 and not f.reads
    assert handoff(f).status_code == 503 and not f.reads
    f.store.put("private", NEXT)
    entry = decision(f)
    assert entry.status_code == 200 and len(f.reads) == 1
    assert all(value not in entry.content.decode() for value in (KEY, NEXT, f.token))
    assert handoff(f).json()["access_token"] == NEXT and len(f.reads) == 2


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "disabled",
        "definition",
        "file",
        "applied",
        "fingerprint",
        "logout",
        "class",
        "owner",
    ],
)
def test_withdrawn_installation_or_actor_denies_before_any_key_read(personal, change):
    f = personal
    fields = {}
    if change == "missing":
        f.manifest_file.unlink()
    elif change == "disabled":
        f.declaration["enabled"] = False
        f.write()
    elif change == "definition":
        f.resources[0]["revision"] += 1
    elif change == "file":
        f.file["policies"].append({"changed": True})
    elif change == "applied":
        f.applied["policies"].append({"changed": True})
    elif change == "fingerprint":
        fields["definition_fingerprint"] = "a" * 64
    elif change == "logout":
        f.stores.identity.logout(f.token)
    elif change == "class":
        ProjectClass.objects.update(data_class_id="public")
    else:
        User.objects.filter(pk=f.actor["id"]).update(is_active=False)
    response = handoff(f, **fields)
    assert response.status_code in (400, 503) and not f.reads
    assert all(
        value not in response.content.decode() for value in (KEY, NEXT, f.key, f.token)
    )
    assert "no-store" in response["Cache-Control"]


def test_client_cannot_select_uninstalled_contract_or_replace_gateway_identity(
    personal,
):
    assert handoff(personal, installed=False).status_code == 400
    assert handoff(personal, key="").status_code == 401
    assert not personal.reads
    personal.declaration["enabled"] = False
    personal.write()
    assert handoff(personal).status_code == 503
    # The previously approved, private unactivated handoff remains a distinct
    # operator contract; its route never activates the protected listener.
    assert handoff(personal, path="/internal/runtime/provider-token").status_code == 200


@pytest.mark.parametrize(
    "provider", ["anthropic", {"custom": {"formats": [{"type": "completions"}]}}]
)
def test_only_fixed_cloud_personal_providers_are_enrolled(installed, provider):
    installed.resources[0]["value"]["provider"] = provider
    installed.fp = installed.enroll("personal")
    assert decision(installed, True).status_code == (
        200 if provider == "anthropic" else 503
    )


@pytest.mark.parametrize("fault", ["http", "auth", "global-key-metadata"])
def test_personal_enrollment_cannot_borrow_a_plaintext_or_shared_key(installed, fault):
    f = installed
    if fault == "http":
        f.resources[0]["value"]["params"]["baseUrl"] = "http://provider.invalid/v1"
    elif fault == "auth":
        f.resources[0]["value"]["auth"] = False
    f.fp = f.enroll("personal")
    if fault == "global-key-metadata":
        f.declaration["models"]["private"]["key_name"] = "key-" + "a" * 32
        f.declaration["models"]["private"]["key_digest"] = "a" * 64
        f.write()
    assert decision(f).status_code == 503
