"""Estimated cost of a developer's usage, worked out when it is read (ADR 029).

Cost is tokens times the shipped list price of the provider's model. It is an
estimate in US dollars: discounts, negotiated, batch, cache and regional prices
are never applied, and cached-input and reasoning tokens count as ordinary
input and output tokens. Each model gets one ``cost_status``:

- ``estimate``: a cloud model Keeplane added with a row in the price list;
- ``local``: a model Keeplane added from a local runner, never priced;
- ``no_list_price``: any other model, including a cloud model with no row and a
  model whose provider Keeplane didn't record.

Each period also gets ``cost_partial``: true when an ``estimate`` leaves out
some of that period's tokens because they were counted before Keeplane recorded
the model's provider. A model name with no usage yet in the UTC hour its
provider was recorded is priced from that hour; otherwise from the next one.
"""

import logging
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.db.models import Q, Sum
from model_registry import prices
from model_registry.models import ModelApproval, ModelOrigin

from .models import UsageTotal

ESTIMATE = "estimate"
LOCAL = "local"
NO_LIST_PRICE = "no_list_price"

log = logging.getLogger(__name__)


def price_list():
    try:
        return prices.shipped()
    except prices.PriceListError as error:
        # A broken list is a release bug; usage still shows, with no costs.
        log.error("The shipped price list was refused: %s", error)
        return None


def first_priced_hour(recorded, hour_priced=False):
    """The first hourly total that holds only usage from after ``recorded``.

    A total covers its whole UTC hour, so the hour the origin was recorded in
    may hold earlier usage under the same name. It is priced when no usage
    held the name in that hour when the origin was recorded (``hour_priced``),
    or when the origin was recorded exactly on the hour.
    """
    recorded = recorded.astimezone(dt_timezone.utc)
    hour = recorded.replace(minute=0, second=0, microsecond=0)
    return hour if hour_priced or hour == recorded else hour + timedelta(hours=1)


def priced_tokens(user_id, model_id, since, day_start, month_start):
    """Tokens counted from ``since`` on, for today and this month.

    Usage from before Keeplane recorded the model's provider is never priced,
    so a name reused after a local model was removed can't price its tokens.
    """
    today = Q(hour__gte=max(day_start, since))
    sums = UsageTotal.objects.filter(
        user_id=user_id, model_id=model_id, hour__gte=max(month_start, since)
    ).aggregate(
        today_input=Sum("input_tokens", filter=today, default=0),
        today_output=Sum("output_tokens", filter=today, default=0),
        month_input=Sum("input_tokens", default=0),
        month_output=Sum("output_tokens", default=0),
    )
    return (
        (sums["today_input"], sums["today_output"]),
        (sums["month_input"], sums["month_output"]),
    )


def pricing(origin, listed):
    """The cost status and list price for a model's recorded origin.

    ``origin`` is the model's approval row, or empty when there is none (a
    model removed since). Only a cloud model with an exact provider and model
    name row is priced; a local model never is, whatever its name.
    """
    if origin.get("origin") == ModelOrigin.LOCAL:
        return LOCAL, None
    if origin.get("origin") == ModelOrigin.CLOUD and listed:
        price = listed.price(origin["provider"], origin["provider_model"])
        if price is not None:
            return ESTIMATE, price
    return NO_LIST_PRICE, None


def add_estimates(user_id, usage, day_start, month_start):
    """Add the price list's date and each model's estimated cost to ``usage``."""
    listed = price_list()
    usage["price_list"] = (
        {"date": listed.date.isoformat(), "currency": listed.currency}
        if listed
        else None
    )
    origins = {
        row["model_id"]: row
        for row in ModelApproval.objects.filter(
            pk__in=[item["model"] for item in usage["models"]]
        ).values(
            "model_id",
            "origin",
            "provider",
            "provider_model",
            "origin_recorded_at",
            "origin_hour_priced",
        )
    }
    for item in usage["models"]:
        origin = origins.get(item["model"], {})
        status, price = pricing(origin, listed)
        item["cost_status"] = status
        if price is None:
            for period in ("today", "this_month"):
                item[period]["estimated_cost"] = None
                item[period]["cost_partial"] = False
            continue
        priced = priced_tokens(
            user_id,
            item["model"],
            first_priced_hour(
                origin["origin_recorded_at"], origin["origin_hour_priced"]
            ),
            day_start,
            month_start,
        )
        for period, (input_tokens, output_tokens) in zip(
            ("today", "this_month"), priced, strict=True
        ):
            counts = item[period]
            counts["estimated_cost"] = str(price.cost(input_tokens, output_tokens))
            # Some of this period's tokens predate the recorded origin, so the
            # cost leaves them out.
            counts["cost_partial"] = (input_tokens, output_tokens) != (
                counts["input_tokens"],
                counts["output_tokens"],
            )
    return usage
