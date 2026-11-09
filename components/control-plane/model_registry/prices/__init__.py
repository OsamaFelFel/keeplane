"""The list-price table that ships with Keeplane (ADR 029).

``list-prices.json`` is copied by hand from each provider's public pricing
page. Nothing is fetched at runtime. A registered model is priced only when
Keeplane recorded, at add time, that it is a cloud model, which provider it is
on and the provider's own model name; the lookup is an exact match on those two
values. A local runner's model is never priced.
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

LIST_PATH = Path(__file__).with_name("list-prices.json")
CURRENCY = "USD"
# Each provider's prices must come from that provider's own pages.
SOURCE_HOSTS = {
    "openai": {"openai.com", "developers.openai.com", "platform.openai.com"},
    "anthropic": {"platform.claude.com", "claude.com", "www.anthropic.com"},
}
ROW_FIELDS = {
    "provider",
    "model",
    "input_per_million",
    "output_per_million",
    "source",
    "checked",
}
LIST_FIELDS = {"version", "currency", "date", "note", "prices"}
PRICE = re.compile(r"(0|[1-9][0-9]{0,3})(\.[0-9]{1,4})?")
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}")
MILLION = Decimal(1_000_000)
# Costs are given to a millionth of a dollar; the CLI rounds for display.
COST_STEP = Decimal("0.000001")


class PriceListError(Exception):
    pass


@dataclass(frozen=True)
class ListPrice:
    input_per_million: Decimal
    output_per_million: Decimal

    def cost(self, input_tokens, output_tokens):
        """The estimated cost in US dollars, rounded half up to a millionth."""
        total = (
            Decimal(input_tokens) * self.input_per_million
            + Decimal(output_tokens) * self.output_per_million
        ) / MILLION
        return total.quantize(COST_STEP, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PriceList:
    date: date
    currency: str
    prices: dict

    def price(self, provider, provider_model):
        """The row for exactly this provider and model name, or None."""
        return self.prices.get((provider, provider_model))


def _date(value, where):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise PriceListError(f"{where}: write the date as YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise PriceListError(f"{where}: {value} is not a real date") from None


def _price(value, where):
    if not isinstance(value, str) or not PRICE.fullmatch(value):
        raise PriceListError(
            f'{where}: write US dollars per million tokens as text, such as "2.50"'
        )
    try:
        return Decimal(value)
    except InvalidOperation:  # pragma: no cover - the pattern rules it out
        raise PriceListError(f"{where}: {value} is not a price") from None


def parse(document):
    """Check a price list document and return it, or raise PriceListError."""
    if not isinstance(document, dict) or set(document) != LIST_FIELDS:
        raise PriceListError(
            "The price list needs exactly: " + ", ".join(sorted(LIST_FIELDS))
        )
    if document["version"] != 1:
        raise PriceListError("Only price list version 1 is supported")
    if document["currency"] != CURRENCY:
        raise PriceListError("Prices must be in US dollars (USD)")
    list_date = _date(document["date"], "date")
    rows = document["prices"]
    if not isinstance(rows, list) or not rows:
        raise PriceListError("The price list has no prices")
    prices = {}
    checked_dates = []
    for number, row in enumerate(rows, 1):
        where = f"row {number}"
        if not isinstance(row, dict) or set(row) != ROW_FIELDS:
            raise PriceListError(
                f"{where} needs exactly: " + ", ".join(sorted(ROW_FIELDS))
            )
        provider, model = row["provider"], row["model"]
        if provider not in SOURCE_HOSTS:
            raise PriceListError(f"{where}: unknown provider {provider!r}")
        if not isinstance(model, str) or not MODEL_NAME.fullmatch(model):
            raise PriceListError(f"{where}: write the provider's exact model name")
        source = row["source"]
        parts = urlsplit(source) if isinstance(source, str) else None
        if (
            parts is None
            or parts.scheme != "https"
            or parts.hostname not in SOURCE_HOSTS[provider]
            or parts.username
            or parts.password
            or parts.port
        ):
            raise PriceListError(
                f"{where}: the source must be the provider's own https pricing page"
            )
        checked = _date(row["checked"], where + " checked")
        if (provider, model) in prices:
            raise PriceListError(f"{where}: {provider} {model} is listed twice")
        prices[(provider, model)] = ListPrice(
            _price(row["input_per_million"], where + " input"),
            _price(row["output_per_million"], where + " output"),
        )
        checked_dates.append(checked)
    if min(checked_dates) != list_date:
        # The label shows this date, so it must be the stalest row's date: a
        # list never looks fresher than its oldest price.
        raise PriceListError("The list's date must be its oldest row's checked date")
    return PriceList(list_date, CURRENCY, prices)


def load(path=LIST_PATH):
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PriceListError(f"The price list can't be read: {error}") from None
    return parse(document)


@lru_cache(maxsize=1)
def shipped():
    """The price list in this Keeplane release, checked once per process."""
    return load()
