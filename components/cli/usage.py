"""Report each turn's usage and show the developer their own usage (Spec 009 ST31).

ADR 029: after each turn ``keeplane code`` sends one report per model, with
the counts its relay read from the gateway's answers. ``keeplane usage`` shows
the signed-in developer's own tokens and estimated cost per model, for today
and this month in the machine's time zone. The server takes the developer from
the sign-in, and there is no way to ask for anyone else (D191).
"""

import json
import os
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

if __package__:
    from .credential_profile import opened
    from .server_connection import ConnectionError, request
else:
    from credential_profile import opened
    from server_connection import ConnectionError, request

ROUTE = "/api/runtime/usage"
COUNTS = ("input_tokens", "output_tokens", "requests", "requests_without_usage")
PERIOD_FIELDS = frozenset(COUNTS) | {"estimated_cost", "cost_partial"}
STATUSES = ("estimate", "local", "no_list_price")
MAX_MODELS = 1000
# The same zone names the server takes.
ZONE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+){0,2}")
COST = re.compile(r"\d{1,15}\.\d{1,6}")
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# Wording decided by the associate product owner (9 November).
ESTIMATE_LABEL = (
    "Costs are estimates from each provider's list price (price list of "
    "{date}), in US dollars."
)
NO_LIST_PRICE = "no list price"
LOCAL_COST = "—"
NO_TOKENS = "{model}: {count} requests didn't report tokens, so its totals may be low."
NO_TOKENS_ONE = "{model}: 1 request didn't report tokens, so its totals may be low."
# Product questions for the associate product owner (task 009-10).
PARTIAL_COST = "{model}: some of its tokens couldn't be priced, so its cost may be low."
HEADING = "Your usage for today, {today}, and this month, {month}{utc}."
NOTHING_YET = "You haven't used any models this month."
NOT_RECORDED = (
    "Keeplane couldn't record this task's usage of {models}, so "
    "`keeplane usage` may show less than you used."
)
NO_USAGE_ROUTE = (
    "This Keeplane server doesn't show usage yet. Ask your admin to update it."
)


def report_turn(issuer, project_id, credential, counts):
    """Send one report per model the turn used; return a warning line or "".

    A report that fails never fails the turn: the developer is told that
    their usage may be low (ADR 029).
    """
    failed = []
    for model in sorted(counts or {}):
        row = counts[model]
        if not isinstance(row, dict) or not row.get("requests"):
            continue
        payload = {"project_id": project_id, "model": model}
        payload.update({name: row.get(name, 0) for name in COUNTS})
        try:
            request(
                issuer, ROUTE, credential, method="POST", expected=204, payload=payload
            )
        except ConnectionError:  # The server, the network or an expired sign-in.
            failed.append(model)
    if not failed:
        return ""
    return NOT_RECORDED.format(models=joined(failed)) + "\n"


def joined(names):
    """ "A", "A and B", "A, B and C": the decided way to list models."""
    if len(names) < 2:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def zone_from_path(path):
    """``Area/City`` from a zoneinfo file's path, or None."""
    parts = str(path).replace("\\", "/").split("/zoneinfo/")
    if len(parts) < 2:
        return None
    return parts[-1].removeprefix("posix/").removeprefix("right/")


def machine_time_zone(environ=None, localtime="/etc/localtime", named="/etc/timezone"):
    """The machine's time zone as an IANA name, or None when it can't be read.

    ``TZ`` first (a name, or a path into a zoneinfo folder), then the
    ``/etc/localtime`` link (Linux and macOS), then ``/etc/timezone``.
    """
    environ = os.environ if environ is None else environ
    candidates = []
    value = environ.get("TZ")
    if value:
        value = value.removeprefix(":")
        candidates.append(zone_from_path(value) if value.startswith("/") else value)
    try:
        link = Path(localtime)
        if link.is_symlink():
            candidates.append(zone_from_path(os.path.realpath(link)))
    except OSError:
        pass
    try:
        with open(named, encoding="utf-8") as handle:
            candidates.append(handle.readline(128).strip())
    except (OSError, UnicodeError):
        pass
    for name in candidates:
        if name and ZONE_NAME.fullmatch(name) and len(name) <= 64:
            return name
    return None


def valid_period(period, status):
    if not isinstance(period, dict) or set(period) != PERIOD_FIELDS:
        return False
    if not all(type(period[name]) is int and period[name] >= 0 for name in COUNTS):
        return False
    if period["requests_without_usage"] > period["requests"]:
        return False
    if type(period["cost_partial"]) is not bool:
        return False
    cost = period["estimated_cost"]
    if status == "estimate":
        return isinstance(cost, str) and COST.fullmatch(cost) is not None
    return cost is None and period["cost_partial"] is False


def checked(body):
    """The server's usage answer, or ConnectionError if it isn't one."""
    try:
        data = json.loads(body)
        if (
            not isinstance(data, dict)
            or set(data) != {"time_zone", "today", "month", "price_list", "models"}
            or not isinstance(data["time_zone"], str)
            or not isinstance(data["today"], str)
            or not isinstance(data["month"], str)
            or not isinstance(data["models"], list)
            or len(data["models"]) > MAX_MODELS
        ):
            raise ValueError
        date.fromisoformat(data["today"])
        if not re.fullmatch(r"\d{4}-\d{2}", data["month"]):
            raise ValueError
        date.fromisoformat(data["month"] + "-01")
        listed = data["price_list"]
        if listed is not None:
            if (
                not isinstance(listed, dict)
                or set(listed) != {"date", "currency"}
                or listed["currency"] != "USD"
                or not isinstance(listed["date"], str)
            ):
                raise ValueError
            date.fromisoformat(listed["date"])
        names = []
        for row in data["models"]:
            if (
                not isinstance(row, dict)
                or set(row) != {"model", "cost_status", "today", "this_month"}
                or not isinstance(row["model"], str)
                or not 0 < len(row["model"]) <= 256
                or any(
                    c.isspace() or ord(c) < 32 or ord(c) == 127 for c in row["model"]
                )
                or row["cost_status"] not in STATUSES
                or not valid_period(row["today"], row["cost_status"])
                or not valid_period(row["this_month"], row["cost_status"])
            ):
                raise ValueError
            names.append(row["model"])
        if len(set(names)) != len(names):
            raise ValueError
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ConnectionError("The server returned invalid usage.") from None
    return data


def fetch(issuer, credential, zone):
    """Usage in ``zone``; (data, True) when the server used UTC instead."""
    if zone is not None:
        try:
            return checked(
                request(issuer, ROUTE, credential, query={"tz": zone})
            ), False
        except ConnectionError as error:
            if error.status != 400:
                raise
            # This server doesn't know the machine's zone name: use UTC.
    return checked(request(issuer, ROUTE, credential)), True


def long_date(value):
    day = date.fromisoformat(value)
    return str(day.day) + " " + MONTHS[day.month - 1] + " " + str(day.year)


def long_month(value):
    year, month = value.split("-")
    return MONTHS[int(month) - 1] + " " + year


def dollars(value):
    """$ and the estimate: cents from $1, otherwise to the millionth of a dollar."""
    amount = Decimal(value)
    if amount >= 1:
        return "$" + format(
            amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ","
        )
    text = format(amount.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), "f")
    whole, fraction = text.split(".")
    fraction = fraction.rstrip("0").ljust(2, "0")
    return "$" + whole + "." + fraction


def cost(status, period):
    if status == "local":
        return LOCAL_COST
    if status == "no_list_price":
        return NO_LIST_PRICE
    return dollars(period["estimated_cost"])


def table(data, utc=False):
    """The usage table, its estimate label and the notes below it."""
    heading = HEADING.format(
        today=long_date(data["today"]),
        month=long_month(data["month"]),
        utc=" (UTC)" if utc else "",
    )
    if not data["models"]:
        return heading + "\n\n" + NOTHING_YET
    rows = [("Model", "Period", "Input tokens", "Output tokens", "Estimated cost")]
    for row in data["models"]:
        for label, period, name in (
            ("Today", row["today"], row["model"]),
            ("This month", row["this_month"], ""),
        ):
            rows.append(
                (
                    name,
                    label,
                    format(period["input_tokens"], ","),
                    format(period["output_tokens"], ","),
                    cost(row["cost_status"], period),
                )
            )
    widths = [max(len(row[index]) for row in rows) for index in range(5)]
    lines = []
    for row in rows:
        cells = [
            row[0].ljust(widths[0]),
            row[1].ljust(widths[1]),
            row[2].rjust(widths[2]),
            row[3].rjust(widths[3]),
            row[4],
        ]
        lines.append("  ".join(cells).rstrip())
    notes = []
    priced = [row for row in data["models"] if row["cost_status"] == "estimate"]
    if priced and data["price_list"] is not None:
        notes.append(ESTIMATE_LABEL.format(date=long_date(data["price_list"]["date"])))
    for row in data["models"]:
        missing = row["this_month"]["requests_without_usage"]
        if missing == 1:
            notes.append(NO_TOKENS_ONE.format(model=row["model"]))
        elif missing:
            notes.append(
                NO_TOKENS.format(model=row["model"], count=format(missing, ","))
            )
        if row["today"]["cost_partial"] or row["this_month"]["cost_partial"]:
            notes.append(PARTIAL_COST.format(model=row["model"]))
    text = heading + "\n\n" + "\n".join(lines)
    if notes:
        text += "\n\n" + "\n".join(notes)
    return text


def show(profile_path, zone=None):
    """``keeplane usage``: the signed-in developer's own usage, as a table."""
    zone = machine_time_zone() if zone is None else zone
    with opened(profile_path) as profile:
        credential = profile.load()
        try:
            data, utc = fetch(credential.issuer, credential.access_token, zone)
        except ConnectionError as error:
            if error.status == 404:
                raise ConnectionError(NO_USAGE_ROUTE, 404) from None
            raise
        output = table(data, utc=utc or zone is None)
        for secret in (credential.access_token, credential.refresh_token):
            output = output.replace(secret, "[redacted]")
        return output
