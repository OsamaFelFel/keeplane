"""Estimated cost in a developer's own usage, on the test SQLite database.

Spec 009 ST31 (D186, D189), ADR 029, task 009-09. Cases DU-C1 to DU-C11 in
developer-usage-cases.md. Models are added through Keeplane's real add flow:
cloud models against the cloud-provider fixture, local ones from a runner,
under a test price row.
"""

from datetime import timedelta
from functools import partial
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from model_registry import catalog as catalog_module
from model_registry import prices
from model_registry.models import ModelApproval
from model_registry.provider_probe import provider_answers
from model_registry.registration import ModelManagement
from usage import totals

from tests.integration.test_developer_usage import NOW, get, usage  # noqa: F401
from tests.integration.test_personal_model_registration import (  # noqa: F401
    provider,
)
from tests.unit.test_model_registration_ids import Gateway

TEST_LIST = {
    "version": 1,
    "currency": "USD",
    "date": "2026-10-01",
    "note": "Test prices",
    "prices": [
        {
            "provider": "openai",
            "model": "test-gpt",
            "input_per_million": "3",
            "output_per_million": "15",
            "source": "https://developers.openai.com/api/docs/pricing",
            "checked": "2026-10-01",
        },
        {
            "provider": "anthropic",
            "model": "test-claude",
            "input_per_million": "1",
            "output_per_million": "5",
            "source": "https://platform.claude.com/docs/en/about-claude/pricing",
            "checked": "2026-10-15",
        },
    ],
}
UPSTREAM = {"openai": "test-gpt", "anthropic": "test-claude"}


@pytest.fixture
def priced(usage, provider, monkeypatch):  # noqa: F811
    """Keeplane's add flow, the usage clock and a test price list."""
    monkeypatch.setattr(prices, "shipped", lambda: prices.parse(TEST_LIST))
    # Origins are recorded on the same moving clock as the usage totals.
    monkeypatch.setattr(
        catalog_module, "timezone", SimpleNamespace(now=lambda: usage.clock.now)
    )
    registrar = ModelManagement(
        usage.stores.catalog,
        usage.stores.classes,
        Gateway(),
        None,
        "managed",
        None,
        "",
        set(),
        {"openai": provider["url"], "anthropic": provider["url"]},
        "",
        provider_probe=partial(provider_answers, allow_loopback_http=True),
    )
    registrar.local_runner = lambda *_: (200, {})
    registrar.runner_context = lambda *_: None
    usage.registrar = registrar
    return usage


def add_cloud(priced, name, source, model):
    status, body = priced.registrar.add(
        {"name": name, "model": model, "source": source, "key_choice": "personal"}
    )
    assert status == 200, body


def add_local(priced, name):
    status, body = priced.registrar.add(
        {
            "name": name,
            "model": "test-gpt",
            "source": "runner",
            "address": "http://runner.test:11434",
        }
    )
    assert status == 200, body


def used(priced, model, input_tokens, output_tokens, requests=1, at=None, by=None):
    totals.add(
        (by or priced.developer).id,
        model,
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "requests": requests,
            "requests_without_usage": 0,
        },
        now=at or priced.clock.now,
    )


def models(priced):
    response = get(priced)
    assert response.status_code == 200
    return response.json(), {item["model"]: item for item in response.json()["models"]}


@pytest.mark.parametrize("source", ["openai", "anthropic"])
def test_du_c1_a_listed_cloud_model_shows_an_estimated_cost(priced, source):
    add_cloud(priced, "cloud-coder", source, UPSTREAM[source])
    approval = ModelApproval.objects.get(pk="cloud-coder")
    assert (approval.origin, approval.provider, approval.provider_model) == (
        "cloud",
        source,
        UPSTREAM[source],
    )
    # Added at 15:20 under a name with no usage yet, so its first hour, 15:00,
    # is priced too: the 15:25 total counts.
    assert approval.origin_hour_priced
    used(priced, "cloud-coder", 1234, 567, at=NOW + timedelta(minutes=5))
    priced.clock.now = NOW + timedelta(days=1)
    used(priced, "cloud-coder", 2_000_000, 10)
    body, found = models(priced)
    # The label's date is the list's (oldest row) date; costs are in US dollars.
    assert body["price_list"] == {"date": "2026-10-01", "currency": "USD"}
    item = found["cloud-coder"]
    assert item["cost_status"] == "estimate"
    if source == "openai":  # $3 in, $15 out per million
        today, month = "6.000150", "6.012357"
    else:  # $1 in, $5 out per million
        today, month = "2.000050", "2.004119"
    assert item["today"]["estimated_cost"] == today
    assert item["this_month"]["estimated_cost"] == month
    assert item["this_month"]["input_tokens"] == 2_001_234
    assert item["this_month"]["output_tokens"] == 577
    assert not item["today"]["cost_partial"]
    assert not item["this_month"]["cost_partial"]


def test_du_c2_a_local_model_shows_tokens_and_no_cost(priced):
    # Its runner model name matches a listed cloud price; it is still not priced.
    add_local(priced, "local-coder")
    approval = ModelApproval.objects.get(pk="local-coder")
    assert (approval.origin, approval.provider, approval.provider_model) == (
        "local",
        "",
        "",
    )
    used(priced, "local-coder", 5000, 700, requests=2)
    _, found = models(priced)
    item = found["local-coder"]
    assert item["cost_status"] == "local"
    assert item["today"]["estimated_cost"] is None
    assert item["this_month"]["estimated_cost"] is None
    assert item["today"]["input_tokens"] == 5000
    assert item["today"]["output_tokens"] == 700


@pytest.mark.parametrize("source", ["openai", "anthropic"])
def test_du_c3_a_cloud_model_with_no_row_shows_no_list_price(priced, source):
    add_cloud(priced, "unlisted", source, "not-in-the-list")
    # A listed name from the other provider must not match.
    other = {"openai": "anthropic", "anthropic": "openai"}[source]
    add_cloud(priced, "wrong-provider", source, UPSTREAM[other])
    used(priced, "unlisted", 100, 10)
    used(priced, "wrong-provider", 100, 10)
    body, found = models(priced)
    assert body["price_list"]["date"] == "2026-10-01"
    for name in ("unlisted", "wrong-provider"):
        assert found[name]["cost_status"] == "no_list_price"
        assert found[name]["today"]["estimated_cost"] is None
        assert found[name]["today"]["input_tokens"] == 100


def test_du_c4_a_model_whose_provider_wasnt_recorded_is_not_priced(priced):
    # "coder" was approved without Keeplane adding it (as before 009-09, or a
    # model registered directly in the gateway). "removed" has no approval.
    used(priced, "coder", 1000, 100)
    used(priced, "removed", 1000, 100)
    _, found = models(priced)
    for name in ("coder", "removed"):
        assert found[name]["cost_status"] == "no_list_price"
        assert found[name]["this_month"]["estimated_cost"] is None


def test_du_c5_usage_from_before_the_provider_was_recorded_is_not_priced(priced):
    # A local model used this name earlier in the month and earlier in this
    # very hour (15:05), was removed, and at 15:20 a cloud model was added
    # under the same name and used at 15:25.
    used(priced, "reused", 9_000_000, 9_000_000, at=NOW - timedelta(days=2))
    used(priced, "reused", 1_000_000, 0, at=NOW - timedelta(hours=1))
    used(priced, "reused", 500_000, 500_000, at=NOW - timedelta(minutes=15))
    add_cloud(priced, "reused", "openai", "test-gpt")
    used(priced, "reused", 7, 7, at=NOW + timedelta(minutes=5))
    priced.clock.now = NOW + timedelta(hours=1)
    used(priced, "reused", 1000, 1000)
    _, found = models(priced)
    assert not ModelApproval.objects.get(pk="reused").origin_hour_priced
    item = found["reused"]
    assert item["cost_status"] == "estimate"
    assert item["this_month"]["input_tokens"] == 10_501_007
    assert item["today"]["input_tokens"] == 1_501_007
    # The 15:00 total mixes the local model's tokens with the cloud model's,
    # so only totals from 16:00 on are priced: the 1,000 + 1,000 tokens.
    assert item["today"]["estimated_cost"] == "0.018000"
    assert item["this_month"]["estimated_cost"] == "0.018000"
    assert item["today"]["cost_partial"] and item["this_month"]["cost_partial"]


def test_du_c5_another_developers_usage_this_hour_keeps_the_hour_unpriced(priced):
    # Another developer used the name at 15:05 under an earlier model; the
    # hour is checked for every developer, so this developer's 15:25 tokens in
    # the same hour are not priced either.
    used(
        priced, "reused", 1_000_000, 0, at=NOW - timedelta(minutes=15), by=priced.other
    )
    add_cloud(priced, "reused", "openai", "test-gpt")
    assert not ModelApproval.objects.get(pk="reused").origin_hour_priced
    used(priced, "reused", 1000, 1000, at=NOW + timedelta(minutes=5))
    _, found = models(priced)
    item = found["reused"]
    assert item["today"]["input_tokens"] == 1000
    assert item["today"]["estimated_cost"] == "0.000000"
    assert item["today"]["cost_partial"] and item["this_month"]["cost_partial"]


def test_du_c5_a_model_added_exactly_on_the_hour_is_priced_from_that_hour(priced):
    on_the_hour = NOW.replace(minute=0)
    used(priced, "cloud-coder", 1_000_000, 0, at=on_the_hour - timedelta(minutes=1))
    priced.clock.now = on_the_hour
    add_cloud(priced, "cloud-coder", "openai", "test-gpt")
    used(priced, "cloud-coder", 1000, 1000, at=on_the_hour + timedelta(minutes=30))
    _, found = models(priced)
    item = found["cloud-coder"]
    assert item["today"]["estimated_cost"] == "0.018000"
    assert item["today"]["cost_partial"]
    # Today without the earlier hour: a later day holds only priced usage.
    priced.clock.now = on_the_hour + timedelta(days=1)
    used(priced, "cloud-coder", 1000, 1000)
    _, found = models(priced)
    item = found["cloud-coder"]
    assert item["today"]["estimated_cost"] == "0.018000"
    assert not item["today"]["cost_partial"]
    assert item["this_month"]["estimated_cost"] == "0.036000"
    assert item["this_month"]["cost_partial"]


def test_du_c6_setting_a_model_up_again_keeps_its_recorded_provider(priced):
    add_cloud(priced, "cloud-coder", "openai", "test-gpt")
    before = ModelApproval.objects.values(
        "origin",
        "provider",
        "provider_model",
        "origin_recorded_at",
        "origin_hour_priced",
    ).get(pk="cloud-coder")
    priced.clock.now = NOW + timedelta(hours=3)
    approval = ModelApproval.objects.get(pk="cloud-coder")
    priced.stores.catalog.approve(
        "cloud-coder",
        [],
        approval.gateway_fingerprint,
        owned_by_keeplane=True,
        key_choice="personal",
    )
    after = ModelApproval.objects.values(
        "origin",
        "provider",
        "provider_model",
        "origin_recorded_at",
        "origin_hour_priced",
    ).get(pk="cloud-coder")
    assert after == before


def test_du_c6_a_definition_replaced_outside_keeplane_loses_its_provider(priced):
    add_cloud(priced, "cloud-coder", "openai", "test-gpt")
    # Someone replaces the gateway definition directly, then an admin sets
    # the model up again in Keeplane.
    record = priced.registrar.gateway.records["cloud-coder"]
    record["value"]["params"]["model"] = "something-else"
    record["revision"] += 1
    status, body = priced.registrar.setup("cloud-coder", {"key_choice": "personal"})
    assert status == 200, body
    approval = ModelApproval.objects.get(pk="cloud-coder")
    assert not approval.owned_by_keeplane
    assert (
        approval.origin,
        approval.provider,
        approval.provider_model,
        approval.origin_recorded_at,
    ) == ("", "", "", None)
    priced.clock.now = NOW + timedelta(hours=2)
    used(priced, "cloud-coder", 1000, 1000)
    _, found = models(priced)
    assert found["cloud-coder"]["cost_status"] == "no_list_price"
    assert found["cloud-coder"]["today"]["estimated_cost"] is None
    with pytest.raises(ValueError, match="Only a model Keeplane adds"):
        priced.stores.catalog.approve(
            "cloud-coder", [], "definition", added_from=("local", "", "")
        )


def test_du_c10_a_new_name_is_priced_from_its_first_hour(priced):
    # Usage in an earlier hour, under the name, doesn't matter: only the hour
    # the provider is recorded in decides.
    used(priced, "fresh", 1_000_000, 0, at=NOW - timedelta(hours=1))
    add_cloud(priced, "fresh", "openai", "test-gpt")
    approval = ModelApproval.objects.get(pk="fresh")
    assert approval.origin_recorded_at == NOW and approval.origin_hour_priced
    # A report that lands later in the same hour is this model's own usage.
    used(priced, "fresh", 1000, 1000, at=NOW + timedelta(minutes=5))
    used(priced, "fresh", 1000, 1000, at=NOW + timedelta(minutes=30))
    _, found = models(priced)
    item = found["fresh"]
    assert item["today"]["estimated_cost"] == "0.036000"
    # Only the 14:00 tokens are left out.
    assert item["today"]["cost_partial"]
    priced.clock.now = NOW + timedelta(days=1)
    used(priced, "fresh", 1000, 1000)
    _, found = models(priced)
    item = found["fresh"]
    assert item["today"]["estimated_cost"] == "0.018000"
    assert not item["today"]["cost_partial"]
    assert item["this_month"]["estimated_cost"] == "0.054000"


def test_du_c10_a_name_used_by_nobody_this_hour_has_every_token_priced(priced):
    add_cloud(priced, "fresh", "anthropic", "test-claude")
    used(priced, "fresh", 1000, 1000, at=NOW + timedelta(minutes=1))
    _, found = models(priced)
    item = found["fresh"]
    # $1 in, $5 out per million.
    assert item["today"]["estimated_cost"] == "0.006000"
    assert item["this_month"]["estimated_cost"] == "0.006000"
    assert not item["today"]["cost_partial"]
    assert not item["this_month"]["cost_partial"]


def test_du_c10_a_name_re_added_in_the_same_hour_is_not_priced_from_it(priced):
    # A model is added at 15:20 and used; it is replaced by another model
    # under the same name later in the hour. The second record sees the first
    # model's 15:25 tokens, so the hour is no longer priced.
    add_cloud(priced, "reused", "openai", "test-gpt")
    used(priced, "reused", 1000, 1000, at=NOW + timedelta(minutes=5))
    approval = ModelApproval.objects.get(pk="reused")
    priced.clock.now = NOW + timedelta(minutes=10)
    priced.stores.catalog.approve(
        "reused",
        [],
        approval.gateway_fingerprint,
        owned_by_keeplane=True,
        key_choice="personal",
        added_from=("cloud", "anthropic", "test-claude"),
    )
    again = ModelApproval.objects.get(pk="reused")
    assert again.origin_recorded_at == NOW + timedelta(minutes=10)
    assert not again.origin_hour_priced
    used(priced, "reused", 1000, 1000, at=NOW + timedelta(minutes=15))
    _, found = models(priced)
    item = found["reused"]
    assert item["today"]["input_tokens"] == 2000
    assert item["today"]["estimated_cost"] == "0.000000"
    assert item["today"]["cost_partial"]


def test_du_c10_clearing_the_origin_clears_the_first_hour(priced):
    add_cloud(priced, "cloud-coder", "openai", "test-gpt")
    approval = ModelApproval.objects.get(pk="cloud-coder")
    assert approval.origin_hour_priced
    priced.stores.catalog.approve(
        "cloud-coder", [], approval.gateway_fingerprint, owned_by_keeplane=False
    )
    cleared = ModelApproval.objects.get(pk="cloud-coder")
    assert (cleared.origin, cleared.origin_hour_priced) == ("", False)


def test_du_c7_a_broken_shipped_list_shows_tokens_without_costs(priced, monkeypatch):
    add_cloud(priced, "cloud-coder", "openai", "test-gpt")
    add_local(priced, "local-coder")
    used(priced, "cloud-coder", 100, 10)
    used(priced, "local-coder", 100, 10)

    def broken():
        raise prices.PriceListError("broken")

    monkeypatch.setattr(prices, "shipped", broken)
    body, found = models(priced)
    assert body["price_list"] is None
    assert found["cloud-coder"]["cost_status"] == "no_list_price"
    assert found["local-coder"]["cost_status"] == "local"
    assert found["cloud-coder"]["today"]["input_tokens"] == 100


def test_du_c8_an_origin_that_doesnt_add_up_is_refused(priced):
    catalog = priced.stores.catalog
    for added_from in [
        ("cloud", "google", "test-gpt"),
        ("cloud", "openai", ""),
        ("cloud", "openai", "x" * 257),
        ("local", "openai", "test-gpt"),
        ("remote", "", ""),
        ["local", "", ""],
    ]:
        with pytest.raises(ValueError, match="provider could not be recorded"):
            catalog.approve(
                "bad", [], "definition", owned_by_keeplane=True, added_from=added_from
            )
    assert not ModelApproval.objects.filter(pk="bad").exists()
    for fields in [
        {"origin": "cloud", "provider": "openai", "provider_model": ""},
        {"origin": "local", "provider": "openai", "provider_model": ""},
        {"origin": "cloud", "provider": "openai", "provider_model": "test-gpt"},
    ]:
        with pytest.raises(IntegrityError), transaction.atomic():
            ModelApproval.objects.create(
                model_id="bad", key_choice="none", gateway_fingerprint="d", **fields
            )


@pytest.mark.django_db(transaction=True)
def test_du_c9_existing_approvals_keep_no_recorded_provider_after_the_upgrade():
    before = [("model_registry", "0009_gateway_guard_status")]
    after = [("model_registry", "0010_model_origin")]
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(before)
        old_model = executor.loader.project_state(before).apps.get_model(
            "model_registry", "ModelApproval"
        )
        old_model.objects.create(
            model_id="earlier", key_choice="shared", gateway_fingerprint="definition"
        )
        upgraded = MigrationExecutor(connection)
        upgraded.migrate(after)
        new_model = upgraded.loader.project_state(after).apps.get_model(
            "model_registry", "ModelApproval"
        )
        # An app copy from before the upgrade can still save an approval.
        old_model.objects.create(
            model_id="older-copy", key_choice="none", gateway_fingerprint="definition"
        )
        rows = new_model.objects.values(
            "origin", "provider", "provider_model", "origin_recorded_at"
        )
        for row in rows:
            assert row == {
                "origin": "",
                "provider": "",
                "provider_model": "",
                "origin_recorded_at": None,
            }
        assert rows.count() == 2
    finally:
        MigrationExecutor(connection).migrate(latest)


@pytest.mark.django_db(transaction=True)
def test_du_c11_origins_recorded_before_the_upgrade_keep_the_next_hour_rule():
    before = [("model_registry", "0010_model_origin")]
    after = [("model_registry", "0011_model_origin_hour")]
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    origin = {
        "key_choice": "personal",
        "gateway_fingerprint": "definition",
        "owned_by_keeplane": True,
        "origin": "cloud",
        "provider": "openai",
        "provider_model": "test-gpt",
        "origin_recorded_at": NOW,
    }
    try:
        executor.migrate(before)
        old_model = executor.loader.project_state(before).apps.get_model(
            "model_registry", "ModelApproval"
        )
        old_model.objects.create(model_id="earlier", **origin)
        upgraded = MigrationExecutor(connection)
        upgraded.migrate(after)
        new_model = upgraded.loader.project_state(after).apps.get_model(
            "model_registry", "ModelApproval"
        )
        # An app copy from before the upgrade can still save an approval.
        old_model.objects.create(model_id="older-copy", **origin)
        rows = new_model.objects.values_list("model_id", "origin_hour_priced")
        assert sorted(rows) == [("earlier", False), ("older-copy", False)]
    finally:
        MigrationExecutor(connection).migrate(latest)
