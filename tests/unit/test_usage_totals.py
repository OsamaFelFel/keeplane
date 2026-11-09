"""Usage report caps, retention and time-zone periods (Spec 009 ST31, ADR 029).

Cases DU-U1 to DU-U6 in usage-totals-cases.md.
"""

import zoneinfo
from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from usage import totals

UTC = dt_timezone.utc


def report(**changes):
    body = {
        "input_tokens": 100,
        "output_tokens": 20,
        "requests": 2,
        "requests_without_usage": 0,
    }
    body.update(changes)
    return body


def test_du_u1_a_valid_report_keeps_its_counts():
    assert totals.capped(report(prompt="ignored")) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "requests": 2,
        "requests_without_usage": 0,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"input_tokens": -1},
        {"output_tokens": 2.0},
        {"requests": "2"},
        {"requests": False},
        {"requests": 0},
        {"requests_without_usage": None},
    ],
)
def test_du_u2_counts_must_be_whole_numbers_and_a_request_is_needed(changes):
    with pytest.raises(totals.UsageError):
        totals.capped(report(**changes))


def test_du_u3_numbers_are_lowered_to_the_caps():
    capped = totals.capped(
        report(requests=10**9, requests_without_usage=10**9, input_tokens=10**18)
    )
    assert capped["requests"] == capped["requests_without_usage"] == totals.MAX_REQUESTS
    # Requests that reported no tokens can't carry any.
    assert capped["input_tokens"] == 0
    capped = totals.capped(
        report(requests=3, requests_without_usage=1, output_tokens=10**18)
    )
    assert capped["output_tokens"] == 2 * totals.MAX_TOKENS_PER_REQUEST
    assert (
        totals.capped(report(requests_without_usage=9))["requests_without_usage"] == 2
    )


@pytest.mark.parametrize(
    "now, cutoff",
    [
        (datetime(2026, 11, 9, 15, tzinfo=UTC), datetime(2026, 9, 30, 10, tzinfo=UTC)),
        # Just after a UTC month change, New York is still in November, so all
        # of October is its previous month and is kept.
        (datetime(2026, 12, 1, 3, tzinfo=UTC), datetime(2026, 9, 30, 10, tzinfo=UTC)),
        # UTC-12 is still in November until 1 December 12:00 UTC.
        (
            datetime(2026, 12, 1, 11, 59, tzinfo=UTC),
            datetime(2026, 9, 30, 10, tzinfo=UTC),
        ),
        (datetime(2026, 12, 1, 12, tzinfo=UTC), datetime(2026, 10, 31, 10, tzinfo=UTC)),
        (datetime(2026, 1, 1, 0, tzinfo=UTC), datetime(2025, 10, 31, 10, tzinfo=UTC)),
        (datetime(2026, 1, 1, 12, tzinfo=UTC), datetime(2025, 11, 30, 10, tzinfo=UTC)),
        (datetime(2026, 3, 31, 23, tzinfo=UTC), datetime(2026, 1, 31, 10, tzinfo=UTC)),
    ],
)
def test_du_u4_retention_keeps_this_and_the_previous_month_in_every_zone(now, cutoff):
    assert totals.retention_cutoff(now) == cutoff
    assert totals.current_hour(now.replace(minute=59, second=7)) == now.replace(
        minute=0
    )


@pytest.mark.parametrize(
    "zone, now, today, day_start, month_start",
    [
        (
            "UTC",
            datetime(2026, 11, 9, 15, 20, tzinfo=UTC),
            "2026-11-09",
            datetime(2026, 11, 9, tzinfo=UTC),
            datetime(2026, 11, 1, tzinfo=UTC),
        ),
        (
            "Pacific/Kiritimati",
            datetime(2026, 10, 31, 10, 30, tzinfo=UTC),
            "2026-11-01",
            datetime(2026, 10, 31, 10, tzinfo=UTC),
            datetime(2026, 10, 31, 10, tzinfo=UTC),
        ),
        # Half-hour offset: local midnight is 18:30 UTC, equally near 18:00 and
        # 19:00; the earlier hour is used.
        (
            "Asia/Kolkata",
            datetime(2026, 11, 9, 20, tzinfo=UTC),
            "2026-11-10",
            datetime(2026, 11, 9, 18, tzinfo=UTC),
            datetime(2026, 10, 31, 18, tzinfo=UTC),
        ),
        # UTC+5:45: local midnight is 18:15 UTC, nearest 18:00.
        (
            "Asia/Kathmandu",
            datetime(2026, 11, 9, 20, tzinfo=UTC),
            "2026-11-10",
            datetime(2026, 11, 9, 18, tzinfo=UTC),
            datetime(2026, 10, 31, 18, tzinfo=UTC),
        ),
        # UTC+13:45 in summer: local midnight is 10:15 UTC, nearest 10:00.
        (
            "Pacific/Chatham",
            datetime(2026, 11, 9, 20, tzinfo=UTC),
            "2026-11-10",
            datetime(2026, 11, 9, 10, tzinfo=UTC),
            datetime(2026, 10, 31, 10, tzinfo=UTC),
        ),
        # Newfoundland: UTC-3:30, so midnight is 03:30 UTC and the day starts at
        # 03:00. 1 November began in summer time (UTC-2:30): 02:30, so 02:00.
        (
            "America/St_Johns",
            datetime(2026, 11, 9, 20, tzinfo=UTC),
            "2026-11-09",
            datetime(2026, 11, 9, 3, tzinfo=UTC),
            datetime(2026, 11, 1, 2, tzinfo=UTC),
        ),
        # The day summer time ends in Europe is 25 hours long.
        (
            "Europe/Berlin",
            datetime(2026, 10, 25, 22, 30, tzinfo=UTC),
            "2026-10-25",
            datetime(2026, 10, 24, 22, tzinfo=UTC),
            datetime(2026, 9, 30, 22, tzinfo=UTC),
        ),
    ],
)
def test_du_u5_days_and_months_follow_the_developers_zone(
    zone, now, today, day_start, month_start
):
    local, day, month = totals.periods(zoneinfo.ZoneInfo(zone), now)
    assert (local.date().isoformat(), day, month) == (today, day_start, month_start)


@pytest.mark.parametrize(
    "name",
    [
        "Mars/Olympus",
        "../etc/passwd",
        "/etc/localtime",
        "Europe//Berlin",
        "x" * 65,
        "",
        3,
    ],
)
def test_du_u6_only_known_zone_names_are_accepted(name):
    assert totals.time_zone(None).key == "UTC"
    assert totals.time_zone("America/Argentina/Buenos_Aires").key.endswith("Aires")
    with pytest.raises(totals.UsageError):
        totals.time_zone(name)
