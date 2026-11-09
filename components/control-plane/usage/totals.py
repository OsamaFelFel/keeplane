"""Add usage reports to hourly totals and read them back for one developer.

The caller passes the account established by authentication; nothing here
takes an account from a report. Days and months follow the time zone the
developer asks for. Totals are hourly, so a day or month starts at the UTC
hour nearest local midnight, at most 30 minutes away. In a zone with a
half-hour offset the two hours are equally near and the earlier one is used:
in India (UTC+5:30) the day starts at 18:00 UTC, half an hour before midnight.
"""

import re
import zoneinfo
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.db import IntegrityError, transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import Least
from django.utils import timezone

from .models import UsageTotal

COUNTS = ("input_tokens", "output_tokens", "requests", "requests_without_usage")
# Caps for one report (one turn, one model). Larger numbers are lowered to these.
MAX_REQUESTS = 10_000
MAX_TOKENS_PER_REQUEST = 10_000_000
# No hourly total grows past this, however many reports arrive.
MAX_TOTAL = 10**15
# The zones furthest ahead of (UTC+14) and behind (UTC-12) UTC.
AHEAD = timedelta(hours=14)
BEHIND = timedelta(hours=12)
ZONE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+){0,2}")


class UsageError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def capped(report):
    """Return the four counts of a valid report, lowered to the caps."""
    values = {}
    for name in COUNTS:
        value = report.get(name)
        if type(value) is not int or value < 0:
            raise UsageError(f"Send {name} as a whole number, 0 or more")
        values[name] = value
    if values["requests"] < 1:
        raise UsageError("Send a report for at least one request")
    requests = min(values["requests"], MAX_REQUESTS)
    without = min(values["requests_without_usage"], requests)
    most_tokens = (requests - without) * MAX_TOKENS_PER_REQUEST
    return {
        "input_tokens": min(values["input_tokens"], most_tokens),
        "output_tokens": min(values["output_tokens"], most_tokens),
        "requests": requests,
        "requests_without_usage": without,
    }


def current_hour(now=None):
    now = (now or timezone.now()).astimezone(dt_timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def retention_cutoff(now=None):
    """Totals whose hour starts before this are older than the previous month.

    The zone furthest behind UTC is the last to leave a month, so its current
    month decides which month is "previous" for someone. That previous month
    starts earliest in the zone furthest ahead of UTC, so the cut-off is its
    start there: every developer's previous month is kept whole.
    """
    behind = (now or timezone.now()).astimezone(dt_timezone.utc) - BEHIND
    months = behind.year * 12 + behind.month - 2  # the month before, counted from 0
    year, month = divmod(months, 12)
    return datetime(year, month + 1, 1, tzinfo=dt_timezone.utc) - AHEAD


def delete_old_totals(now=None):
    return UsageTotal.objects.filter(hour__lt=retention_cutoff(now)).delete()[0]


def add(user_id, model_id, counts, now=None):
    """Add one capped report to the developer's total for this hour and model."""
    hour = current_hour(now)
    rows = UsageTotal.objects.filter(user_id=user_id, model_id=model_id, hour=hour)
    increase = {name: Least(F(name) + counts[name], MAX_TOTAL) for name in COUNTS}
    with transaction.atomic():
        if not rows.update(**increase):
            try:
                with transaction.atomic():
                    UsageTotal.objects.create(
                        user_id=user_id, model_id=model_id, hour=hour, **counts
                    )
            except IntegrityError:
                # Another copy created this hour's row first; add to it.
                rows.update(**increase)
        delete_old_totals(now)


def time_zone(name):
    if name is None:
        return zoneinfo.ZoneInfo("UTC")
    if not isinstance(name, str) or not ZONE_NAME.fullmatch(name) or len(name) > 64:
        raise UsageError("Send a time zone such as Europe/Berlin")
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        raise UsageError("Send a time zone such as Europe/Berlin") from None


def nearest_hour(moment):
    """The UTC hour nearest a moment; a moment exactly on the half hour rounds down."""
    moment = moment.astimezone(dt_timezone.utc)
    hour = moment.replace(minute=0, second=0, microsecond=0)
    return hour + timedelta(hours=1) if moment - hour > timedelta(minutes=30) else hour


def periods(zone, now=None):
    """Return the UTC hours that start today and this month in the developer's zone."""
    local = (now or timezone.now()).astimezone(zone)
    day = datetime(local.year, local.month, local.day, tzinfo=zone)
    month = datetime(local.year, local.month, 1, tzinfo=zone)
    return local, nearest_hour(day), nearest_hour(month)


def own_usage(user_id, zone, now=None):
    """The developer's totals per model for today and this month."""
    local, day_start, month_start = periods(zone, now)
    today = Q(hour__gte=day_start)
    sums = {}
    for name in COUNTS:
        sums["month_" + name] = Sum(name)
        sums["today_" + name] = Sum(name, filter=today, default=0)
    rows = (
        UsageTotal.objects.filter(user_id=user_id, hour__gte=month_start)
        .values("model_id")
        .annotate(**sums)
        .order_by("model_id")
    )
    return {
        "time_zone": zone.key,
        "today": local.date().isoformat(),
        "month": local.strftime("%Y-%m"),
        "models": [
            {
                "model": row["model_id"],
                "today": {name: row["today_" + name] for name in COUNTS},
                "this_month": {name: row["month_" + name] for name in COUNTS},
            }
            for row in rows
        ],
    }
