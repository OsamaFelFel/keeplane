"""Explicit runtime bearer logout cannot revoke sessions using ambient cookies."""

from types import SimpleNamespace

import pytest
from django.test import Client, RequestFactory, override_settings
from rest_framework.decorators import api_view
from rest_framework.response import Response

from accounts import authentication
from common.middleware import BrowserCsrfMiddleware
from model_registry import runtime_views


@pytest.fixture
def sessions(domain_services, monkeypatch):
    identity, password = domain_services.identity, "logout-test-password"
    identity.create_user(
        {"username": "logout-developer", "role": "developer", "password": password}
    )
    first = identity.login("logout-developer", password)
    second = identity.login("logout-developer", password)
    monkeypatch.setattr(authentication, "IDENTITY", identity)
    monkeypatch.setattr(runtime_views, "IDENTITY", identity)
    with override_settings(ALLOWED_HOSTS=["testserver"]):
        yield SimpleNamespace(
            identity=identity,
            first=first,
            second=second,
            client=Client(enforce_csrf_checks=True),
        )


def test_logout_revokes_only_its_explicit_bearer_session(sessions):
    sessions.client.cookies["keeplane_session"] = sessions.second
    response = sessions.client.delete(
        "/api/runtime/session", HTTP_AUTHORIZATION="Bearer " + sessions.first
    )
    assert response.status_code == 204 and not response.content
    assert "no-store" in response["Cache-Control"]
    assert sessions.identity.session(sessions.first) is None
    assert sessions.identity.session(sessions.second) is not None
    assert (
        sessions.client.delete(
            "/api/runtime/session", HTTP_AUTHORIZATION="Bearer " + sessions.first
        ).status_code
        == 401
    )


def test_current_runtime_account_requires_live_explicit_bearer(sessions):
    sessions.client.cookies["keeplane_session"] = sessions.first
    assert sessions.client.get("/api/runtime/session").status_code == 401
    response = sessions.client.get(
        "/api/runtime/session", HTTP_AUTHORIZATION="Bearer " + sessions.first
    )
    assert response.status_code == 200
    assert response.json() == sessions.identity.session(sessions.first)
    assert "no-store" in response["Cache-Control"]
    sessions.identity.logout(sessions.first)
    assert (
        sessions.client.get(
            "/api/runtime/session", HTTP_AUTHORIZATION="Bearer " + sessions.first
        ).status_code
        == 401
    )


@pytest.mark.parametrize("header", [None, "Bearer invalid", "Basic invalid"])
def test_cookie_or_invalid_header_cannot_revoke_a_session(sessions, header):
    sessions.client.cookies["keeplane_session"] = sessions.first
    headers = {} if header is None else {"HTTP_AUTHORIZATION": header}
    response = sessions.client.delete("/api/runtime/session", **headers)
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Bearer"
    assert sessions.identity.session(sessions.first) is not None


@pytest.mark.parametrize("path", ["/api/session", "/api/users", "/sign-out"])
def test_runtime_bearer_does_not_exempt_browser_mutations_from_csrf(sessions, path):
    sessions.client.cookies["keeplane_session"] = sessions.first
    response = sessions.client.post(
        path,
        data={},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + sessions.first,
    )
    assert response.status_code == 403 and response.json()["code"] == "csrf_failed"
    assert sessions.identity.session(sessions.first) is not None


def test_marker_without_exact_runtime_authentication_keeps_csrf_checks():
    @authentication.runtime_bearer_only
    @api_view(["POST"])
    def unprotected(request):
        return Response({})

    request = RequestFactory().post("/marked", data={})
    middleware = BrowserCsrfMiddleware(lambda request: None)
    middleware.process_request(request)
    assert middleware.process_view(request, unprotected, (), {}).status_code == 403


def test_logout_rejects_account_claims_without_revoking_either_session(sessions):
    response = sessions.client.delete(
        "/api/runtime/session",
        data={"user_id": "someone-else"},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer " + sessions.first,
    )
    assert response.status_code == 400
    assert sessions.identity.session(sessions.first) is not None
    assert sessions.identity.session(sessions.second) is not None
