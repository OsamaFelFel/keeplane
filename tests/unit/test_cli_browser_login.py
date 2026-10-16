"""Controlled HTTP issuer only; actual Django consent/issuance is tested separately."""

import base64
import hashlib
import json
import socket
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from components.cli import browser_login, keeplane
from components.cli.credential_profile import Profile, ProfileError, opened
from components.cli.server_connection import ConnectionError, NoRedirects


@pytest.fixture
def issuer():
    state = SimpleNamespace(
        actor=str(uuid.uuid4()),
        access="kpc_" + "a" * 43,
        refresh="kpr_" + "b" * 43,
        authorizations=[],
        exchanges=[],
        codes={},
        revocations=0,
        revoke_status=204,
        account_status=200,
        token_status=200,
        token_body=None,
        before_callback=None,
        callback_extra={},
        device_code="synthetic-device-code-" + "d" * 32,
        user_code="ABCD1234",
        device_body=None,
        device_status=200,
        device_errors=[],
        device_starts=0,
        device_polls=[],
        refresh_requests=[],
        expected_refresh=None,
        refresh_client="keeplane-cli",
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, value):
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path.startswith("/oauth/authorize/?"):
                params = {
                    k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()
                }
                state.authorizations.append(params)
                code = "synthetic_code_" + uuid.uuid4().hex
                state.codes[code] = params
                self.send_response(302)
                self.send_header(
                    "Location",
                    params["redirect_uri"]
                    + "?"
                    + urlencode(
                        {"state": params["state"], "code": code, **state.callback_extra}
                    ),
                )
                self.end_headers()
            else:
                state.account_headers = dict(self.headers)
                self.respond(
                    state.account_status,
                    {"id": state.actor, "username": "developer", "role": "developer"},
                )

        def do_POST(self):
            form = {
                k: v[0]
                for k, v in parse_qs(
                    self.rfile.read(int(self.headers["Content-Length"])).decode()
                ).items()
            }
            if self.path == "/oauth/device/":
                state.device_starts += 1
                state.device_headers = dict(self.headers)
                self.respond(
                    state.device_status,
                    state.device_body
                    or {
                        "verification_uri": state.url + "/oauth/confirm-device/",
                        "user_code": state.user_code,
                        "device_code": state.device_code,
                        "expires_in": 1800,
                        "interval": 5,
                        "future_secret": "must_not_be_saved",
                    },
                )
                return
            if form.get("grant_type") == "refresh_token":
                state.refresh_requests.append((form, dict(self.headers)))
                valid = (
                    set(form) == {"grant_type", "client_id", "refresh_token"}
                    and form["client_id"] == state.refresh_client
                    and form["refresh_token"] == state.expected_refresh
                )
                self.respond(
                    state.token_status if valid else 400,
                    state.token_body
                    or {
                        "access_token": state.access,
                        "refresh_token": state.refresh,
                        "token_type": "Bearer",
                        "scope": "runtime",
                        "expires_in": 3600,
                        "ignored": "must_not_be_saved",
                    },
                )
                return
            if form.get("grant_type") == "urn:ietf:params:oauth:grant-type:device_code":
                state.device_polls.append((form, dict(self.headers)))
                if state.device_errors:
                    self.respond(400, state.device_errors.pop(0))
                    return
                if (
                    form.get("device_code") != state.device_code
                    or form.get("client_id") != "keeplane-cli-device"
                ):
                    self.respond(400, {"error": "invalid_grant"})
                    return
                self.respond(
                    state.token_status,
                    state.token_body
                    or {
                        "access_token": state.access,
                        "refresh_token": state.refresh,
                        "token_type": "Bearer",
                        "scope": "runtime",
                        "expires_in": 3600,
                    },
                )
                return
            params = state.codes.pop(form.get("code"), {})
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(form.get("code_verifier", "").encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            valid = (
                self.path == "/oauth/token/"
                and set(form)
                == {"grant_type", "client_id", "code", "code_verifier", "redirect_uri"}
                and form["grant_type"] == "authorization_code"
                and form["client_id"] == "keeplane-cli"
                and form["redirect_uri"] == params.get("redirect_uri")
                and challenge == params.get("code_challenge")
            )
            state.exchanges.append((form, dict(self.headers), valid))
            self.respond(
                state.token_status if valid else 400,
                state.token_body
                or {
                    "access_token": state.access,
                    "refresh_token": state.refresh,
                    "token_type": "bEaReR",
                    "scope": "runtime",
                    "expires_in": 3600.0,
                    "future_secret": "must_not_be_saved",
                    "refresh_token_expires_in": 7200,
                },
            )

        def do_DELETE(self):
            state.revocations += 1
            self.respond(state.revoke_status, b"")

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{http.server_port}"

    def browser(url):
        opener = build_opener(ProxyHandler({}), NoRedirects())
        try:
            opener.open(url, timeout=3)
        except HTTPError as error:
            assert error.code == 302
            location = error.headers["Location"]
            error.close()
        state.callback = location
        if state.before_callback:
            state.before_callback(location, opener)
        with opener.open(location, timeout=3) as response:
            response.read()
        return True

    state.browser = browser
    try:
        yield state
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize("unified", [False, True])
def test_actual_command_pkce_current_actor_private_profile_and_no_secret_output(
    issuer, tmp_path, monkeypatch, capsys, unified
):
    path = tmp_path / "profile"
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setattr(browser_login.webbrowser, "open", issuer.browser)
    prefix = ["keeplane", "login"] if unified else ["browser_login"]
    monkeypatch.setattr(
        "sys.argv", [*prefix, "--server", issuer.url, "--profile", str(path)]
    )
    assert (keeplane.main if unified else browser_login.main)() == 0
    with opened(path) as profile:
        credential = profile.load()
        assert (credential.issuer, credential.actor_id) == (issuer.url, issuer.actor)
        assert (
            credential.access_token == issuer.access
            and credential.refresh_token == issuer.refresh
        )
    assert "future_secret" not in (path / "credential.json").read_text()
    assert "must_not_be_saved" not in (path / "credential.json").read_text()
    output = capsys.readouterr()
    assert (
        issuer.access not in output.out + output.err
        and issuer.refresh not in output.out + output.err
    )
    params = issuer.authorizations[0]
    assert params["response_type"] == "code" and params["scope"] == "runtime"
    assert params["code_challenge_method"] == "S256" and len(params["state"]) == 43
    assert params["redirect_uri"].startswith("http://127.0.0.1:") and params[
        "redirect_uri"
    ].endswith("/callback")
    assert issuer.exchanges[0][2]
    headers = issuer.exchanges[0][1]
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert "Cookie" not in headers and "Authorization" not in headers
    assert issuer.account_headers["Authorization"] == "Bearer " + issuer.access
    assert "Cookie" not in issuer.account_headers
    with pytest.raises(ProfileError, match="signed in"):
        browser_login.login(issuer.url, path, browser=issuer.browser)
    assert len(issuer.exchanges) == 1


def test_foreign_duplicate_wrong_state_and_wrong_host_callbacks_cannot_consume_flow(
    issuer, tmp_path
):
    rejected = []

    def before(location, opener):
        for url, headers in [
            (location.replace("/callback?", "/other?"), {}),
            (location.replace("state=", "state=wrong"), {}),
            (location + "&iss=https%3A%2F%2Fother.invalid", {}),
            (location + "&code=duplicate_code_value", {}),
            (location + "&error=access_denied", {}),
            (location, {"Host": "other.invalid"}),
        ]:
            with pytest.raises(HTTPError) as error:
                opener.open(Request(url, headers=headers), timeout=2)
            rejected.append(error.value.code)
            error.value.close()

    issuer.before_callback = before
    browser_login.login(issuer.url, tmp_path / "profile", browser=issuer.browser)
    assert rejected == [400] * 6 and len(issuer.exchanges) == 1


def test_unknown_callback_members_are_ignored_without_saving_or_echoing(
    issuer, tmp_path, capsys
):
    issuer.callback_extra = {"future_metadata": "unknown_callback_value"}
    path = tmp_path / "profile"
    browser_login.login(issuer.url, path, browser=issuer.browser)
    assert len(issuer.exchanges) == 1 and issuer.exchanges[0][2]
    assert "unknown_callback_value" not in (path / "credential.json").read_text()
    output = capsys.readouterr()
    assert "unknown_callback_value" not in output.out + output.err


@pytest.mark.parametrize(
    "body",
    [
        b'{"access_token":"duplicate","access_token":"again"}',
        b'{"access_token":"bad"}',
        b"[]",
        b"x" * 4097,
    ],
)
def test_bad_token_responses_never_save_or_echo_values(issuer, tmp_path, body):
    issuer.token_body = body
    path = tmp_path / "profile"
    with pytest.raises(ConnectionError) as error:
        browser_login.login(issuer.url, path, browser=issuer.browser)
    assert not (path / "credential.json").exists()
    assert issuer.access not in str(error.value)


@pytest.mark.parametrize(
    "change", ["duplicate", "scope", "type", "zero", "boolean", "huge", "refresh"]
)
def test_required_token_fields_and_duplicate_keys_fail_closed(issuer, tmp_path, change):
    data = {
        "access_token": issuer.access,
        "refresh_token": issuer.refresh,
        "token_type": "Bearer",
        "scope": "runtime",
        "expires_in": 3600,
    }
    field, value = {
        "scope": ("scope", "other"),
        "type": ("token_type", "Basic"),
        "zero": ("expires_in", 0),
        "boolean": ("expires_in", True),
        "huge": ("expires_in", 10**400),
        "refresh": ("refresh_token", "bad"),
    }.get(change, (None, None))
    if field:
        data[field] = value
    raw = json.dumps(data).encode()
    if change == "duplicate":
        raw = raw[:-1] + b',"access_token":"' + issuer.access.encode() + b'"}'
    issuer.token_body = raw
    with pytest.raises(ConnectionError):
        browser_login.login(issuer.url, tmp_path / "profile", browser=issuer.browser)
    assert not (tmp_path / "profile" / "credential.json").exists()


@pytest.mark.parametrize("status", [302, 400, 503])
def test_token_refusal_or_redirect_never_forwards_or_saves(issuer, tmp_path, status):
    issuer.token_status = status
    with pytest.raises(ConnectionError, match="refused the exchange"):
        browser_login.login(issuer.url, tmp_path / "profile", browser=issuer.browser)
    assert (
        len(issuer.exchanges) == 1
        and not (tmp_path / "profile" / "credential.json").exists()
    )


def test_account_or_storage_failure_revokes_issued_pair(issuer, tmp_path, monkeypatch):
    issuer.account_status = 503
    with pytest.raises(ConnectionError):
        browser_login.login(issuer.url, tmp_path / "first", browser=issuer.browser)
    issuer.account_status = 200

    def fail(*args):
        raise OSError("secret path must not be printed")

    monkeypatch.setattr(Profile, "save", fail)
    with pytest.raises(ProfileError):
        browser_login.login(issuer.url, tmp_path / "second", browser=issuer.browser)
    assert issuer.revocations == 2
    assert len({row[0]["code_verifier"] for row in issuer.exchanges}) == 2
    assert len({row["state"] for row in issuer.authorizations}) == 2


def test_timeout_closes_drip_fed_callback_and_does_not_exchange(issuer, tmp_path):
    closed = Event()

    def stall(location, opener):
        address = urlsplit(location)
        with socket.create_connection(
            (address.hostname, address.port), timeout=3
        ) as connection:
            connection.sendall(b"GET /callback HTTP/1.1\r\nHost:")
            assert connection.recv(1) == b""
        closed.set()

    issuer.before_callback = stall
    with pytest.raises(ConnectionError, match="timed out"):
        browser_login.login(
            issuer.url, tmp_path / "profile", timeout=1, browser=issuer.browser
        )
    assert closed.wait(2) and not issuer.exchanges
    address = urlsplit(issuer.callback)
    with pytest.raises(OSError):
        socket.create_connection((address.hostname, address.port), timeout=1)


def test_browser_failure_closes_listener_without_token_exchange(issuer, tmp_path):
    with pytest.raises(ConnectionError, match="browser could not open"):
        browser_login.login(issuer.url, tmp_path / "profile", browser=lambda _: False)
    assert not issuer.authorizations and not issuer.exchanges


def test_matching_state_consent_refusal_never_exchanges_or_exports_details(
    issuer, tmp_path
):
    def refuse(location, opener):
        target = urlsplit(location)
        state = parse_qs(target.query)["state"][0]
        with opener.open(
            target._replace(
                query=urlencode(
                    {
                        "state": state,
                        "error": "access_denied",
                        "error_description": issuer.access,
                    }
                )
            ).geturl(),
            timeout=2,
        ):
            pass

    issuer.before_callback = refuse
    with pytest.raises(ConnectionError, match="sign-in was refused") as error:
        browser_login.login(issuer.url, tmp_path / "profile", browser=issuer.browser)
    assert issuer.access not in str(error.value) and not issuer.exchanges


def test_unconfirmed_post_issue_cleanup_reports_the_actual_recovery_gap(
    issuer, tmp_path
):
    issuer.account_status, issuer.revoke_status = 503, 503
    with pytest.raises(
        ConnectionError, match="revocation could not be confirmed"
    ) as error:
        browser_login.login(issuer.url, tmp_path / "profile", browser=issuer.browser)
    assert issuer.revocations == 1 and issuer.access not in str(error.value)
