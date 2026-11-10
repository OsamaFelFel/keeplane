"""The shipped list-price table, its checks, lookups and rounding.

Spec 009 ST31 (D186, D189), ADR 029, task 009-09. Cases LP-U1 to LP-U6 in
list-prices-cases.md.
"""

import copy
import json
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from urllib.parse import urlsplit

import pytest
from model_registry import prices
from usage import costs

ROW = {
    "provider": "openai",
    "model": "test-model",
    "input_per_million": "2.50",
    "output_per_million": "10",
    "source": "https://developers.openai.com/api/docs/pricing",
    "checked": "2026-10-01",
}


def document(*rows, **changes):
    doc = {
        "version": 1,
        "currency": "USD",
        "date": "2026-10-01",
        "note": "Test prices",
        "prices": [copy.deepcopy(row) for row in (rows or [ROW])],
    }
    doc.update(changes)
    return doc


def row(**changes):
    return {**ROW, **changes}


def test_lp_u1_the_shipped_list_passes_its_checks_and_cites_every_price():
    raw = json.loads(prices.LIST_PATH.read_text(encoding="utf-8"))
    listed = prices.shipped()
    assert listed.currency == "USD" and listed.prices
    assert listed.date == min(date.fromisoformat(r["checked"]) for r in raw["prices"])
    assert len(listed.prices) == len(raw["prices"])
    for item in raw["prices"]:
        source = urlsplit(item["source"])
        assert source.scheme == "https"
        assert source.hostname in prices.SOURCE_HOSTS[item["provider"]]
    # Only the providers Keeplane's cloud add flow supports are listed.
    assert {provider for provider, _ in listed.prices} <= {"openai", "anthropic"}


@pytest.mark.parametrize(
    "doc,message",
    [
        ({**document(), "extra": 1}, "needs exactly"),
        ({k: v for k, v in document().items() if k != "note"}, "needs exactly"),
        (document(version=2), "version 1"),
        (document(currency="EUR"), "US dollars"),
        (document(date="1 October 2026"), "YYYY-MM-DD"),
        (document(date="2026-02-30"), "not a real date"),
        (document(prices=[]), "no prices"),
        (document(row(provider="google")), "unknown provider"),
        (document(row(model="")), "exact model name"),
        (document(row(model=" test-model")), "exact model name"),
        (document(row(model="a/b")), "exact model name"),
        (document(row(input_per_million=2.5)), "as text"),
        (document(row(input_per_million="-1")), "as text"),
        (document(row(input_per_million="1e3")), "as text"),
        (document(row(output_per_million="0.123456")), "as text"),
        (document(row(output_per_million="10000")), "as text"),
        (document(row(output_per_million="NaN")), "as text"),
        (document(row(source="http://developers.openai.com/pricing")), "own https"),
        (document(row(source="https://example.com/openai-prices")), "own https"),
        (document(row(source="https://platform.claude.com/pricing")), "own https"),
        (document(row(source="https://user@openai.com/pricing")), "own https"),
        (document(row(source=None)), "own https"),
        (document(row(checked="2026-13-01")), "not a real date"),
        ({**document(), "prices": [row(), {**row(), "extra": 1}]}, "needs exactly"),
        (document(row(), row(output_per_million="11")), "listed twice"),
        (document(date="2026-09-01"), "oldest row"),
        (document(row(), row(model="other", checked="2026-09-30")), "oldest row"),
        ([], "needs exactly"),
    ],
)
def test_lp_u2_a_list_that_breaks_a_rule_is_refused(doc, message):
    with pytest.raises(prices.PriceListError, match=message):
        prices.parse(doc)


def test_lp_u2_rows_checked_after_the_lists_date_are_allowed():
    listed = prices.parse(
        document(row(), row(model="newer", checked="2026-11-01"), date="2026-10-01")
    )
    assert listed.date == date(2026, 10, 1)


def test_lp_u2_an_unreadable_file_is_refused(tmp_path):
    with pytest.raises(prices.PriceListError, match="can't be read"):
        prices.load(tmp_path / "missing.json")
    broken = tmp_path / "list.json"
    broken.write_text("{not json")
    with pytest.raises(prices.PriceListError, match="can't be read"):
        prices.load(broken)


def test_lp_u3_lookups_match_the_provider_and_model_name_exactly():
    listed = prices.parse(
        document(
            row(),
            row(
                provider="anthropic",
                model="claude-test",
                source="https://platform.claude.com/docs/en/about-claude/pricing",
            ),
        )
    )
    assert listed.price("openai", "test-model") == prices.ListPrice(
        Decimal("2.50"), Decimal(10)
    )
    assert listed.price("anthropic", "claude-test") is not None
    for provider, model in [
        ("anthropic", "test-model"),
        ("openai", "Test-Model"),
        ("openai", "test-model "),
        ("openai", "test-model-2026"),
        ("openai", "test"),
        ("", "test-model"),
    ]:
        assert listed.price(provider, model) is None


@pytest.mark.parametrize(
    "input_tokens,output_tokens,expected",
    [
        (0, 0, "0.000000"),
        (1, 0, "0.000003"),  # 0.0000025 rounds half up
        (0, 1, "0.000010"),
        (1234, 567, "0.008755"),  # 0.003085 + 0.00567
        (1_000_000, 1_000_000, "12.500000"),
        (10**15, 10**15, "12500000000.000000"),
    ],
)
def test_lp_u4_costs_round_half_up_to_a_millionth_of_a_dollar(
    input_tokens, output_tokens, expected
):
    price = prices.parse(document()).price("openai", "test-model")
    assert str(price.cost(input_tokens, output_tokens)) == expected


RECORDED = datetime(2026, 11, 1, tzinfo=dt_timezone.utc)


@pytest.mark.parametrize(
    "origin,status",
    [
        (
            {
                "origin": "cloud",
                "provider": "openai",
                "provider_model": "test-model",
                "origin_recorded_at": RECORDED,
            },
            "estimate",
        ),
        (
            {
                "origin": "cloud",
                "provider": "openai",
                "provider_model": "unlisted",
                "origin_recorded_at": RECORDED,
            },
            "no_list_price",
        ),
        (
            {
                "origin": "local",
                "provider": "",
                "provider_model": "",
                "origin_recorded_at": RECORDED,
            },
            "local",
        ),
        (
            {
                "origin": "",
                "provider": "",
                "provider_model": "",
                "origin_recorded_at": None,
            },
            "no_list_price",
        ),
        ({}, "no_list_price"),
    ],
)
def test_lp_u5_only_a_listed_cloud_model_is_priced(origin, status):
    listed = prices.parse(document())
    found, price = costs.pricing(origin, listed)
    assert found == status
    assert (price is not None) == (status == "estimate")


def test_lp_u5_a_local_model_is_never_priced_even_if_its_name_is_listed():
    listed = prices.parse(document())
    # A local model whose runner name equals a listed cloud model's name.
    local = {"origin": "local", "provider": "openai", "provider_model": "test-model"}
    assert costs.pricing(local, listed) == ("local", None)


def test_lp_u6_without_a_readable_list_no_model_is_priced(monkeypatch):
    def broken():
        raise prices.PriceListError("broken")

    monkeypatch.setattr(prices, "shipped", broken)
    assert costs.price_list() is None
    cloud = {"origin": "cloud", "provider": "openai", "provider_model": "test-model"}
    assert costs.pricing(cloud, None) == ("no_list_price", None)
    assert costs.pricing({"origin": "local"}, None) == ("local", None)
