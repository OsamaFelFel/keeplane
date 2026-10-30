"""Only a current saved key's provider response can change its refused state."""

from types import SimpleNamespace

import pytest
from accounts.models import User
from common.errors import StorageUnavailable
from django.db import DatabaseError, connection, transaction
from model_registry.developer_keys import (
    DeveloperKeyRefused,
    DeveloperKeyUnverified,
    DjangoDeveloperKeyStore,
)
from model_registry.models import DeveloperProviderKey

from tests.integration.test_provider_key_validation import KEY, setup
from tests.integration.test_provider_key_validation import provider as provider

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(params=["openAI", "anthropic"])
def saved(request, provider, tmp_path, monkeypatch):
    validator, gateway = setup(provider, request.param)
    monkeypatch.setattr("integrations.gateway.keys.os.fchown", lambda *args: None)
    owner = User.objects.create(username="saved-key-owner", role="developer")
    directory = tmp_path / "keys"
    store = DjangoDeveloperKeyStore(owner.pk, str(directory), validate_key=validator)
    store.put("model", KEY)
    row = DeveloperProviderKey.objects.get(owner=owner, model_id="model")
    return SimpleNamespace(
        store=store, row=row, provider=provider, gateway=gateway,
        directory=directory, validator=validator,
    )


@pytest.mark.parametrize("status", [401, 403])
def test_explicit_refusal_persists_and_success_restores_saved_key(saved, status):
    original = saved.row.key_name
    saved.provider["mode"] = status
    result = saved.store.check("model")
    assert result == {"model_id": "model", "status": "refused", "cleanup_pending": False}
    assert saved.store.status("model", registration_only=True) == result
    assert len(saved.provider["calls"]) == 2
    assert (saved.directory / original).read_text() == KEY
    with pytest.raises(StorageUnavailable):
        saved.store.resolve("model", expected_definition_fingerprint=saved.row.validation_fingerprint)
    assert len(saved.provider["calls"]) == 2
    saved.provider["mode"] = "accepted"
    assert saved.store.check("model")["status"] == "added"
    assert saved.store.resolve(
        "model", expected_definition_fingerprint=saved.row.validation_fingerprint
    ).for_provider() == KEY
    saved.row.refresh_from_db()
    assert saved.row.key_name == original and not saved.row.refused


def test_missing_key_check_is_read_only_and_has_no_provider_contact(saved):
    before = len(saved.provider["calls"])
    assert saved.store.check("another-model")["status"] == "missing"
    assert len(saved.provider["calls"]) == before
    assert DeveloperProviderKey.objects.count() == 1


@pytest.mark.parametrize("prior", [False, True])
@pytest.mark.parametrize("mode", [429, 500, "redirect", "invalid"])
def test_unverified_response_keeps_previous_verdict_and_saved_file(saved, prior, mode):
    DeveloperProviderKey.objects.update(refused=prior)
    saved.provider["mode"] = mode
    with pytest.raises(DeveloperKeyUnverified):
        saved.store.check("model")
    saved.row.refresh_from_db()
    assert saved.row.refused is prior
    assert (saved.directory / saved.row.key_name).read_text() == KEY


@pytest.mark.parametrize("when", ["before", "after-refusal"])
def test_changed_definition_records_no_verdict(saved, when):
    if when == "before":
        saved.gateway.resource["revision"] += 1
    else:
        saved.provider["mode"] = 401

        def change_after_contact():
            if len(saved.provider["calls"]) == 2:
                saved.gateway.resource["revision"] += 1

        saved.gateway.before_read = change_after_contact
    with pytest.raises(DeveloperKeyUnverified):
        saved.store.check("model")
    saved.row.refresh_from_db()
    assert not saved.row.refused
    assert len(saved.provider["calls"]) == (1 if when == "before" else 2)


def test_rejected_replacement_does_not_change_old_verdict(saved):
    saved.provider["mode"] = 401
    with pytest.raises(DeveloperKeyRefused):
        saved.store.put("model", KEY + "-replacement")
    assert saved.store.status("model", registration_only=True)["status"] == "added"
    saved.store.check("model")
    with pytest.raises(DeveloperKeyRefused):
        saved.store.put("model", KEY + "-replacement")
    assert saved.store.status("model", registration_only=True)["status"] == "refused"
    saved.provider["mode"] = "accepted"
    assert saved.store.put("model", KEY + "-replacement")["status"] == "added"
    saved.row.refresh_from_db()
    assert not saved.row.refused and (saved.directory / saved.row.key_name).read_text() == KEY + "-replacement"


def test_failed_commit_cannot_change_refusal_or_files(saved, monkeypatch):
    saved.provider["mode"] = 401
    with monkeypatch.context() as patch:
        patch.setattr(connection, "commit", lambda: (_ for _ in ()).throw(DatabaseError("commit failed")))
        with pytest.raises(StorageUnavailable):
            saved.store.check("model")
    saved.row.refresh_from_db()
    assert not saved.row.refused and (saved.directory / saved.row.key_name).read_text() == KEY


def test_outer_transaction_and_missing_private_file_prevent_provider_contact(saved):
    with transaction.atomic(), pytest.raises(RuntimeError):
        saved.store.check("model")
    (saved.directory / saved.row.key_name).unlink()
    with pytest.raises(StorageUnavailable):
        saved.store.check("model")
    assert len(saved.provider["calls"]) == 1
    saved.row.refresh_from_db()
    assert not saved.row.refused
