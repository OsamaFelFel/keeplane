"""A developer's own usage over HTTP, on the test SQLite database.

Spec 009 ST31 (D191, ADR 029). Cases DU-01 to DU-21 in developer-usage-cases.md;
the separate-process SQLite and PostgreSQL cases are in
test_developer_usage_storage.py.
"""

import json
import uuid
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from types import SimpleNamespace

import pytest
from accounts import authentication
from accounts.models import User
from data_classes.models import ProjectClass, Settings
from django.apps import apps
from django.db import DatabaseError
from django.test import Client, override_settings
from django.urls import URLResolver, get_resolver
from model_registry import prices, runtime_views
from model_registry.fingerprints import fingerprint
from model_registry.models import ModelApproval
from model_registry.policy import DjangoModelPolicy, ModelPolicyUnavailable
from projects.services import DjangoProjectStore
from usage import totals
from usage.models import UsageTotal

PATH = "/api/runtime/usage"
NOW = datetime(2026, 11, 9, 15, 20, tzinfo=dt_timezone.utc)


def account(stores, username, role="developer"):
    password = username + "-usage-password"
    user = stores.identity.create_user(
        {"username": username, "role": role, "password": password}
    )
    return SimpleNamespace(
        id=user["id"], token=stores.identity.login(username, password)
    )


@pytest.fixture
def usage(domain_services, monkeypatch):
    stores = domain_services
    developer, other = account(stores, "usage-dev"), account(stores, "usage-other")
    project = str(uuid.uuid4())
    DjangoProjectStore().register_use(
        User.objects.get(username="first-admin").pk, project, "Usage"
    )
    resources = [{"id": name, "revision": 1} for name in ("coder", "outside")]
    stores.catalog.approve("coder", [], fingerprint("coder", resources))
    state = SimpleNamespace(models=200, resources=200)
    gateway = SimpleNamespace(
        models=lambda: (state.models, {"data": [{"id": r["id"]} for r in resources]}),
        resources=lambda: (state.resources, {"resources": resources}),
    )
    monkeypatch.setattr(authentication, "IDENTITY", stores.identity)
    monkeypatch.setattr(
        runtime_views, "model_policy", lambda: DjangoModelPolicy(gateway)
    )
    clock = SimpleNamespace(now=NOW)
    # Only the usage clock moves; sign-in expiry keeps the real time.
    monkeypatch.setattr(totals, "timezone", SimpleNamespace(now=lambda: clock.now))
    with override_settings(ALLOWED_HOSTS=["testserver"]):
        yield SimpleNamespace(
            client=Client(enforce_csrf_checks=True),
            developer=developer,
            other=other,
            project=project,
            state=state,
            resources=resources,
            stores=stores,
            clock=clock,
        )


def report(**changes):
    body = {
        "model": "coder",
        "input_tokens": 1200,
        "output_tokens": 300,
        "requests": 3,
        "requests_without_usage": 0,
    }
    body.update(changes)
    return body


def post(usage, body, token=None, project=None):
    body = {"project_id": project or usage.project, **body}
    return usage.client.post(
        PATH,
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + (token or usage.developer.token),
    )


def get(usage, query="?tz=UTC", token=None):
    return usage.client.get(
        PATH + query, HTTP_AUTHORIZATION="Bearer " + (token or usage.developer.token)
    )


def counts(input_tokens, output_tokens, requests, without=0):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "requests": requests,
        "requests_without_usage": without,
    }


NO_COST = {"estimated_cost": None, "cost_partial": False}


def test_du_01_reports_add_up_in_the_hour_and_read_back(usage):
    assert post(usage, report()).status_code == 204
    assert post(usage, report(input_tokens=800, output_tokens=200)).status_code == 204
    usage.clock.now = NOW - timedelta(hours=2)
    assert (
        post(
            usage,
            report(
                requests=1, requests_without_usage=1, input_tokens=0, output_tokens=0
            ),
        ).status_code
        == 204
    )
    usage.clock.now = NOW
    assert UsageTotal.objects.count() == 2
    response = get(usage)
    assert response.status_code == 200 and "no-store" in response["Cache-Control"]
    # "coder" was approved without Keeplane recording its provider, so it
    # has no list price (task 009-09; the cost cases are DU-C1 to DU-C8).
    assert response.json() == {
        "time_zone": "UTC",
        "today": "2026-11-09",
        "month": "2026-11",
        "price_list": {"date": prices.shipped().date.isoformat(), "currency": "USD"},
        "models": [
            {
                "model": "coder",
                "cost_status": "no_list_price",
                "today": {
                    **counts(2000, 500, 7, 1),
                    "estimated_cost": None,
                    "cost_partial": False,
                },
                "this_month": {
                    **counts(2000, 500, 7, 1),
                    "estimated_cost": None,
                    "cost_partial": False,
                },
            }
        ],
    }


def test_du_02_only_the_signed_in_developers_totals_come_back(usage):
    assert post(usage, report()).status_code == 204
    assert (
        post(usage, report(input_tokens=5), token=usage.other.token).status_code == 204
    )
    mine = get(usage).json()["models"]
    theirs = get(usage, token=usage.other.token).json()["models"]
    assert mine[0]["today"]["input_tokens"] == 1200
    assert theirs[0]["today"]["input_tokens"] == 5
    # There is no parameter for another account, so asking for one is refused.
    for query in (f"?tz=UTC&user={usage.other.id}", f"?account_id={usage.other.id}"):
        assert get(usage, query).status_code == 400


def test_du_03_an_account_id_in_the_report_is_ignored(usage):
    body = report(
        account_id=usage.other.id, user=usage.other.id, user_id=usage.other.id
    )
    assert post(usage, body).status_code == 204
    row = UsageTotal.objects.get()
    assert str(row.user_id) == usage.developer.id
    assert get(usage, token=usage.other.token).json()["models"] == []


def test_du_04_an_admin_sees_only_their_own_usage(usage):
    admin = account(usage.stores, "usage-admin", role="admin")
    assert post(usage, report()).status_code == 204
    assert get(usage, token=admin.token).json()["models"] == []
    # The only usage route is the developer's own; no admin route reads totals.
    assert [route for route in routes(get_resolver()) if "usage" in route] == [
        "api/runtime/usage"
    ]


def routes(resolver, prefix=""):
    for pattern in resolver.url_patterns:
        route = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            yield from routes(pattern, route)
        else:
            yield route


@pytest.mark.parametrize(
    "body, status",
    [
        (report(model="outside"), 403),
        (report(model="never-set-up"), 403),
        (report(project_id=str(uuid.uuid4())), 403),
        (report(project_id="not-a-project"), 403),
    ],
)
def test_du_05_a_model_or_project_the_developer_may_not_use_is_refused(
    usage, body, status
):
    response = usage.client.post(
        PATH,
        data=json.dumps({"project_id": usage.project, **body}),
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + usage.developer.token,
    )
    assert response.status_code == status
    assert not UsageTotal.objects.exists()


@pytest.mark.parametrize("down", ["models", "resources"])
def test_du_06_usage_is_recorded_while_the_gateway_is_down(usage, down):
    """A turn that ran before the gateway went down is still counted."""
    setattr(usage.state, down, 503)
    assert post(usage, report()).status_code == 204
    assert UsageTotal.objects.get().requests == 3


@pytest.mark.parametrize(
    "model", ["outside", "never-set-up", "unsaved-definition", "restricted"]
)
def test_du_19_with_the_gateway_down_keeplanes_own_policy_still_refuses(usage, model):
    """Only set-up models allowed for the project's class, from Keeplane's data."""
    usage.state.models = 503
    usage.stores.classes.set_enabled(True)
    ProjectClass.objects.create(project_id=usage.project, data_class_id="confidential")
    # An approval whose gateway definition was cleared, as when a model stops
    # being owned by Keeplane.
    usage.stores.catalog.approve("unsaved-definition", [], "saved-definition")
    ModelApproval.objects.filter(pk="unsaved-definition").update(gateway_fingerprint="")
    usage.stores.catalog.approve("restricted", ["Public"], "saved-definition")
    response = post(usage, report(model=model))
    assert response.status_code == 403
    assert response.json() == {"error": "This model is not eligible for the project"}
    # The class rule holds for an approved model too.
    assert post(usage, report()).status_code == 403
    assert not UsageTotal.objects.exists()
    other = str(uuid.uuid4())
    assert post(usage, report(), project=other).status_code == 403
    assert not UsageTotal.objects.exists()


def test_du_20_with_the_gateway_answering_its_current_definition_still_counts(
    usage,
):
    """The gateway's definition is checked whenever the gateway can be read."""
    usage.resources[0]["revision"] = 2  # Changed outside Keeplane.
    assert post(usage, report()).status_code == 403
    assert not UsageTotal.objects.exists()
    usage.state.models = 503
    # Without the gateway that comparison can't be made; a report sends nothing.
    assert post(usage, report()).status_code == 204


def test_du_21_a_policy_problem_not_from_the_gateway_records_nothing(
    usage, monkeypatch
):
    usage.state.models = 503

    def broken(*args, **kwargs):
        raise ModelPolicyUnavailable("Model setup is incomplete")

    monkeypatch.setattr(DjangoModelPolicy, "_decide", broken)
    response = post(usage, report())
    assert response.status_code == 503
    assert response.json() == {"error": "Model policy is unavailable"}
    monkeypatch.undo()
    usage.state.models = 503

    def database_down(*args, **kwargs):
        raise DatabaseError("Unavailable database")

    monkeypatch.setattr(Settings.objects, "select_for_update", database_down)
    assert post(usage, report()).status_code == 503
    assert not UsageTotal.objects.exists()


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("header", [None, "Basic x", "Bearer invalid"])
def test_du_07_cookies_and_claim_headers_do_not_authenticate(usage, method, header):
    usage.client.cookies["keeplane_session"] = usage.developer.token
    usage.client.cookies["sessionid"] = usage.developer.token
    headers = {"HTTP_X_USER_ID": usage.developer.id, "HTTP_X_ROLE": "admin"}
    if header:
        headers["HTTP_AUTHORIZATION"] = header
    if method == "get":
        response = usage.client.get(PATH + "?tz=UTC", **headers)
    else:
        response = usage.client.post(
            PATH,
            data=json.dumps({"project_id": usage.project, **report()}),
            content_type="application/json",
            **headers,
        )
    assert response.status_code == 401 and response["WWW-Authenticate"] == "Bearer"
    assert not UsageTotal.objects.exists()


def test_du_08_no_prompt_answer_or_path_is_stored(usage):
    secret = "please-do-not-store-this-prompt"
    body = report(
        prompt=secret,
        answer=secret,
        path="/home/dev/" + secret,
        repo="git@example.com:" + secret,
        project_name=secret,
    )
    assert post(usage, body).status_code == 204
    row = UsageTotal.objects.values().get()
    assert set(row) == {
        "id",
        "user_id",
        "model_id",
        "hour",
        "input_tokens",
        "output_tokens",
        "requests",
        "requests_without_usage",
    }
    assert secret not in json.dumps(row, default=str)
    assert row["hour"] == NOW.replace(minute=0)
    assert secret not in get(usage).content.decode()


@pytest.mark.parametrize(
    "changes",
    [
        {"input_tokens": -1},
        {"output_tokens": 1.5},
        {"requests": "3"},
        {"requests": True},
        {"requests": 0},
        {"requests_without_usage": None},
        {"model": ""},
        {"model": "m" * 257},
        {"model": 7},
    ],
)
def test_du_09_malformed_reports_are_refused(usage, changes):
    assert post(usage, report(**changes)).status_code == 400
    assert not UsageTotal.objects.exists()


def test_du_10_large_numbers_are_capped(usage):
    huge = report(
        input_tokens=10**18,
        output_tokens=10**18,
        requests=10**9,
        requests_without_usage=10**9 + 5,
    )
    assert post(usage, huge).status_code == 204
    row = UsageTotal.objects.get()
    assert row.requests == totals.MAX_REQUESTS
    assert row.requests_without_usage == totals.MAX_REQUESTS
    assert row.input_tokens == row.output_tokens == 0
    big = report(input_tokens=10**18, requests=2)
    assert post(usage, big).status_code == 204
    row.refresh_from_db()
    assert row.input_tokens == 2 * totals.MAX_TOKENS_PER_REQUEST
    UsageTotal.objects.update(input_tokens=totals.MAX_TOTAL - 1)
    assert post(usage, big).status_code == 204
    row.refresh_from_db()
    assert row.input_tokens == totals.MAX_TOTAL


def test_du_11_days_and_months_follow_the_requested_time_zone(usage):
    def total(hour, tokens):
        UsageTotal.objects.create(
            user_id=usage.developer.id,
            model_id="coder",
            hour=hour,
            input_tokens=tokens,
            requests=1,
        )

    total(datetime(2026, 11, 9, 15, tzinfo=dt_timezone.utc), 1)  # 10:00 New York
    total(datetime(2026, 11, 9, 3, tzinfo=dt_timezone.utc), 10)  # 8 Nov 22:00 NY
    total(datetime(2026, 11, 1, 2, tzinfo=dt_timezone.utc), 100)  # 31 Oct in NY
    total(datetime(2026, 10, 31, 23, tzinfo=dt_timezone.utc), 1000)  # 1 Nov Tokyo
    utc = get(usage, "?tz=UTC").json()["models"][0]
    new_york = get(usage, "?tz=America/New_York").json()["models"][0]
    tokyo = get(usage, "?tz=Asia/Tokyo").json()
    assert (utc["today"]["input_tokens"], utc["this_month"]["input_tokens"]) == (
        11,
        111,
    )
    assert (
        new_york["today"]["input_tokens"],
        new_york["this_month"]["input_tokens"],
    ) == (1, 11)
    # 15:20 UTC is 00:20 on 10 November in Tokyo; the 15:00 UTC hour is today.
    assert tokyo["today"] == "2026-11-10"
    assert tokyo["models"][0]["today"]["input_tokens"] == 1
    assert tokyo["models"][0]["this_month"]["input_tokens"] == 1111


def test_du_16_a_day_starts_at_the_utc_hour_nearest_local_midnight(usage):
    def total(hour, tokens):
        UsageTotal.objects.create(
            user_id=usage.developer.id,
            model_id="coder",
            hour=hour,
            input_tokens=tokens,
            requests=1,
        )

    # Kathmandu is UTC+5:45: 9 November starts at 8 November 18:15 UTC, so the
    # 18:00 UTC hour (23:45 local) is counted as 9 November.
    total(datetime(2026, 11, 8, 18, tzinfo=dt_timezone.utc), 1)
    total(datetime(2026, 11, 8, 17, tzinfo=dt_timezone.utc), 10)
    # 1 November starts at 31 October 18:15 UTC, so the 18:00 hour is November.
    total(datetime(2026, 10, 31, 18, tzinfo=dt_timezone.utc), 100)
    total(datetime(2026, 10, 31, 17, tzinfo=dt_timezone.utc), 1000)
    kathmandu = get(usage, "?tz=Asia/Kathmandu").json()
    assert kathmandu["today"] == "2026-11-09"
    assert kathmandu["models"][0]["today"]["input_tokens"] == 1
    assert kathmandu["models"][0]["this_month"]["input_tokens"] == 111
    # India (UTC+5:30) is a tie between 18:00 and 19:00; the earlier hour is used.
    india = get(usage, "?tz=Asia/Kolkata").json()["models"][0]
    assert india["today"]["input_tokens"] == 1
    assert india["this_month"]["input_tokens"] == 111


def test_du_17_just_after_a_utc_month_change_the_previous_month_is_kept(usage):
    def total(hour):
        return UsageTotal.objects.create(
            user_id=usage.other.id, model_id="coder", hour=hour, requests=1
        )

    # At 1 December 03:00 UTC it is still November in New York, so October is
    # its previous month and must be kept whole.
    usage.clock.now = datetime(2026, 12, 1, 3, tzinfo=dt_timezone.utc)
    october = [
        total(datetime(2026, 10, day, hour, tzinfo=dt_timezone.utc))
        for day, hour in ((1, 0), (1, 4), (15, 12), (31, 23))
    ]
    september = total(datetime(2026, 9, 30, 9, tzinfo=dt_timezone.utc))
    assert post(usage, report()).status_code == 204
    left = set(UsageTotal.objects.values_list("pk", flat=True))
    assert {row.pk for row in october} <= left and september.pk not in left
    new_york = get(usage, "?tz=America/New_York", token=usage.other.token).json()
    assert new_york["month"] == "2026-11" and new_york["models"] == []


@pytest.mark.parametrize("step", ["access", "add", "read"])
def test_du_18_a_storage_outage_is_reported_as_unavailable(usage, monkeypatch, step):
    from usage import views

    def unavailable(*args, **kwargs):
        raise DatabaseError("database is down")

    if step == "access":
        monkeypatch.setattr(views, "organization_project_access", unavailable)
    elif step == "add":
        monkeypatch.setattr(totals, "add", unavailable)
    else:
        monkeypatch.setattr(totals, "own_usage", unavailable)
    response = get(usage) if step == "read" else post(usage, report())
    assert response.status_code == 503
    assert response.json() == {"error": "Usage storage is unavailable"}
    assert "no-store" in response["Cache-Control"]


def test_du_12_without_a_time_zone_utc_is_used_and_bad_zones_are_refused(usage):
    assert get(usage, "").json()["time_zone"] == "UTC"
    for zone in ("Mars/Olympus", "../../etc/passwd", "/etc/localtime", "x" * 70, ""):
        assert get(usage, "?tz=" + zone).status_code == 400


def test_du_13_totals_older_than_the_previous_month_are_deleted(usage):
    def total(hour):
        return UsageTotal.objects.create(
            user_id=usage.other.id, model_id="coder", hour=hour, requests=1
        )

    kept = total(datetime(2026, 10, 1, 0, tzinfo=dt_timezone.utc))
    ahead = total(datetime(2026, 9, 30, 10, tzinfo=dt_timezone.utc))  # 1 Oct at UTC+14
    old = total(datetime(2026, 9, 30, 9, tzinfo=dt_timezone.utc))
    assert post(usage, report()).status_code == 204
    left = set(UsageTotal.objects.values_list("pk", flat=True))
    assert {kept.pk, ahead.pk} <= left and old.pk not in left
    older = total(datetime(2026, 8, 1, tzinfo=dt_timezone.utc))
    assert get(usage).status_code == 200
    assert not UsageTotal.objects.filter(pk=older.pk).exists()


def test_du_14_a_removed_account_takes_its_totals_with_it(usage):
    assert post(usage, report()).status_code == 204
    User.objects.filter(pk=usage.developer.id).delete()
    assert not UsageTotal.objects.exists()


@pytest.mark.optional
@pytest.mark.live
@pytest.mark.skipif(
    not apps.is_installed("oauth2_provider"),
    reason="Install the separately pinned CLI OAuth trial dependencies",
)
def test_du_15_a_cli_oauth_sign_in_records_and_reads_its_own_usage(usage):
    from accounts.cli_credentials import access_token, bind_issued_token
    from accounts.models import CliCredentialBinding
    from django.db import transaction
    from django.utils import timezone
    from oauth2_provider.models import AccessToken, Application, set_token_value

    owner = User.objects.get(pk=usage.developer.id)
    app = Application.objects.create(
        client_id="keeplane-cli",
        client_type=Application.CLIENT_PUBLIC,
        authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        redirect_uris="http://127.0.0.1/callback",
        name="Keeplane CLI",
    )
    raw = access_token()
    with transaction.atomic():
        token = AccessToken(
            user=owner,
            application=app,
            scope="runtime",
            expires=timezone.now() + timedelta(hours=1),
        )
        set_token_value(token, raw)
        token.save()
        bind_issued_token(
            CliCredentialBinding.Kind.ACCESS,
            raw,
            owner.pk,
            owner.get_session_auth_hash(),
        )
    with override_settings(CLI_OAUTH_ENABLED=True):
        assert post(usage, report(), token=raw).status_code == 204
        assert get(usage, token=raw).json()["models"][0]["today"]["requests"] == 3
        assert get(usage, token=usage.other.token).json()["models"] == []
