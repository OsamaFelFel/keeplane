"""Django approval storage retains ownership without mirroring the gateway."""

from types import SimpleNamespace

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from model_registry.chat import ask_model
from model_registry.models import ModelApproval
from model_registry.registration import ModelManagement


def test_model_approval_ownership_and_removal(domain_services):
    catalog = domain_services.catalog
    domain_services.classes.set_enabled(True)
    catalog.approve("shared-name", ["Public"], "definition-one")
    assert catalog.get("shared-name")["owned_by_keeplane"] is False
    catalog.approve("shared-name", ["Public"], "definition-one", owned_by_keeplane=True)
    assert catalog.get("shared-name")["owned_by_keeplane"] is True
    assert catalog.remove("shared-name")
    assert catalog.get("shared-name") is None


def test_personal_choice_is_stored_without_any_provider_key(domain_services):
    catalog = domain_services.catalog
    result = catalog.approve("personal-model", [], "definition-one", key_choice="personal")
    assert result["key_choice"] == "personal"
    assert catalog.get("personal-model") == {
        "key_choice": "personal", "approved_classes": [],
        "gateway_fingerprint": "definition-one", "owned_by_keeplane": False,
    }
    with pytest.raises(ValueError, match="supported provider key"):
        catalog.approve("invalid-model", [], "definition-one", key_choice="invalid")
    with pytest.raises(IntegrityError), transaction.atomic():
        ModelApproval.objects.create(model_id="invalid-model", key_choice="invalid")


def test_personal_setup_cannot_dispatch_or_be_downgraded_by_existing_admin_flows(domain_services):
    stores = domain_services
    stores.classes.set_enabled(False)
    stores.catalog.approve("personal-model", [], "definition-one", key_choice="personal")

    def unexpected(*args, **kwargs):
        raise AssertionError("A Personal downgrade or admin chat contacted the gateway")

    gateway = SimpleNamespace(request=unexpected, resources=unexpected)
    management = ModelManagement(
        stores.catalog, stores.classes, gateway, None, "managed", None, "", [],
        {"openai": "", "anthropic": ""}, "",
    )
    for choice in ("none", "shared"):
        assert management.setup("personal-model", {"key_choice": choice})[0] == 400
    assert ask_model({"model": "personal-model", "prompt": "fixture"}, stores.catalog, gateway, None)[0] == 503
    assert stores.catalog.get("personal-model")["key_choice"] == "personal"


@pytest.mark.django_db(transaction=True)
def test_choice_migration_preserves_existing_approval_records():
    before = [("model_registry", "0002_developer_key_ownership")]
    after = [("model_registry", "0003_personal_provider_key_choice")]
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(before)
        old_model = executor.loader.project_state(before).apps.get_model("model_registry", "ModelApproval")
        for choice in ("none", "shared"):
            old_model.objects.create(
                model_id=choice, key_choice=choice, approved_classes=["Public"],
                gateway_fingerprint="definition-" + choice, owned_by_keeplane=True,
            )
        original = list(old_model.objects.order_by("model_id").values())
        upgraded = MigrationExecutor(connection)
        upgraded.migrate(after)
        new_model = upgraded.loader.project_state(after).apps.get_model("model_registry", "ModelApproval")
        assert list(new_model.objects.order_by("model_id").values()) == original
    finally:
        MigrationExecutor(connection).migrate(latest)
