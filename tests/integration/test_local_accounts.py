"""Spec 003 local accounts through the account API, without a running preview."""

from unittest.mock import patch
import uuid

import pytest
from django.test import Client

from accounts.models import User, UserOperation
from accounts.services import DjangoIdentity

ADMIN_PASSWORD = "first-test-password-123"
PASSWORD = "a-local-test-password-123"


@pytest.fixture
def identity(domain_services):
    with patch("common.api.IDENTITY", domain_services.identity):
        yield domain_services.identity


def signed_in(identity, username="first-admin", password=ADMIN_PASSWORD):
    client = Client()
    client.cookies["keeplane_session"] = identity.login(username, password)
    return client


def create(client, username, role="developer", operation_id=None):
    body = {"username": username, "password": PASSWORD, "role": role}
    if operation_id:
        body["operation_id"] = operation_id
    return client.post(
        "/api/users", body, content_type="application/json", HTTP_X_KEEPLANE_ACTION="1"
    )


def change_role(client, user_id, role):
    return client.put(
        f"/api/users/{user_id}/role",
        {"role": role},
        content_type="application/json",
        HTTP_X_KEEPLANE_ACTION="1",
    )


def listed(client, query=""):
    return client.get("/api/users?" + query).json()


def test_la_01_admin_signs_in_and_out(identity):
    client = Client()
    response = client.post(
        "/api/session",
        {"username": "first-admin", "password": ADMIN_PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.cookies["keeplane_session"]["httponly"]
    assert client.get("/api/identity").json()["role"] == "admin"
    assert client.get("/api/users").status_code == 200

    assert client.get("/sign-out").status_code == 405
    assert client.post("/sign-out").status_code == 200
    assert client.get("/api/identity").status_code == 401
    assert client.get("/api/users").status_code == 401


def test_la_02_developer_session_opens_no_admin_api(identity):
    admin = signed_in(identity)
    developer_id = create(admin, "dev-one").json()["id"]
    developer = signed_in(identity, "dev-one", PASSWORD)
    assert developer.get("/api/identity").json() == {
        "id": developer_id,
        "username": "dev-one",
        "role": "developer",
    }
    refused = [
        developer.get("/api/users"),
        create(developer, "dev-two"),
        change_role(developer, developer_id, "admin"),
        developer.get(f"/api/user-operations/{uuid.uuid4()}"),
        developer.get("/api/projects"),
        developer.get("/api/models"),
    ]
    assert [response.status_code for response in refused] == [403] * len(refused)
    assert User.objects.get(pk=developer_id).role == "developer"
    assert not User.objects.filter(username="dev-two").exists()


def test_la_03_sign_in_offers_no_sso_and_no_self_sign_up(identity):
    anonymous = Client()
    options = anonymous.get("/api/auth-options")
    assert options.json()["sso_connected"] is False
    assert options["Cache-Control"] == "no-store"
    before = User.objects.count()
    assert create(anonymous, "self-made").status_code == 401
    for path in ("/api/register", "/api/sign-up", "/api/signup", "/register"):
        assert anonymous.post(path, {}, content_type="application/json").status_code == 404
    assert User.objects.count() == before


def test_la_04_break_glass_admin_is_listed_managed_and_protected(identity):
    client = signed_in(identity)
    row = listed(client, "search=first-admin")["users"]
    assert row == [
        {
            "id": row[0]["id"],
            "username": "first-admin",
            "role": "admin",
            "managed": True,
            "sign_in": "break-glass",
        }
    ]
    first_admin = row[0]["id"]
    assert change_role(client, first_admin, "developer").status_code == 403
    assert change_role(client, first_admin, "admin").status_code == 403
    removal = client.delete(
        f"/api/users/{first_admin}",
        content_type="application/json",
        HTTP_X_KEEPLANE_ACTION="1",
    )
    assert removal.status_code == 403
    # No one can create a look-alike that Users would also show as managed.
    assert create(client, "First-Admin", "admin").status_code == 409
    stored = User.objects.get(pk=first_admin)
    assert (stored.role, stored.is_active) == ("admin", True)
    assert client.get("/api/identity").status_code == 200


def test_la_05_rotation_keeps_the_break_glass_identity(domain_services):
    identity = domain_services.identity
    original = identity.session(identity.login("first-admin", ADMIN_PASSWORD))
    domain_services.secret.write_text("rotated-first-test-password-456\n")
    rotated = DjangoIdentity(domain_services.secret, domain_services.audit)
    with patch("common.api.IDENTITY", rotated):
        client = signed_in(rotated, password="rotated-first-test-password-456")
        rows = listed(client, "search=first-admin")["users"]
    assert [(row["id"], row["role"], row["managed"]) for row in rows] == [
        (original["id"], "admin", True)
    ]
    assert User.objects.filter(username__iexact="first-admin").count() == 1


@pytest.mark.parametrize("role", ["admin", "developer"])
def test_la_06_created_user_appears_with_the_chosen_role(identity, role):
    client = signed_in(identity)
    response = create(client, f"new-{role}", role)
    assert response.status_code == 201
    assert response.json()["role"] == role
    rows = listed(client, f"search=new-{role}")["users"]
    assert [(row["username"], row["role"], row["sign_in"]) for row in rows] == [
        (f"new-{role}", role, "local")
    ]
    assert "password" not in response.content.decode()


@pytest.mark.parametrize("body", [{}, {"role": ""}, {"role": "owner"}, {"role": None}])
def test_la_07_create_needs_an_explicit_known_role(identity, body):
    client = signed_in(identity)
    payload = {"username": "no-role", "password": PASSWORD, **body}
    response = client.post(
        "/api/users", payload, content_type="application/json", HTTP_X_KEEPLANE_ACTION="1"
    )
    assert response.status_code == 400
    assert not User.objects.filter(username="no-role").exists()


def test_la_08_sent_twice_creates_the_user_once(identity):
    client = signed_in(identity)
    operation = str(uuid.uuid4())
    first = create(client, "retried", "admin", operation)
    second = create(client, "retried", "admin", operation)
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json() == second.json()
    assert User.objects.filter(username="retried").count() == 1
    assert UserOperation.objects.filter(pk=operation).count() == 1
    other_details = client.post(
        "/api/users",
        {"username": "retried", "password": PASSWORD, "role": "developer", "operation_id": operation},
        content_type="application/json",
        HTTP_X_KEEPLANE_ACTION="1",
    )
    assert other_details.status_code == 409
    assert User.objects.get(username="retried").role == "admin"


def test_la_09_check_reports_whether_the_user_was_created(identity):
    client = signed_in(identity)
    operation = str(uuid.uuid4())
    assert client.get(f"/api/user-operations/{operation}").json() == {"status": "not_found"}
    created = create(client, "checked", "developer", operation).json()
    assert client.get(f"/api/user-operations/{operation}").json() == {
        "status": "created",
        "user": created,
    }
    other_admin_id = create(client, "second-admin", "admin").json()["id"]
    other = signed_in(identity, "second-admin", PASSWORD)
    assert other.get(f"/api/user-operations/{operation}").json() == {"status": "not_found"}
    assert create(other, "checked", "developer", operation).status_code == 409
    assert other_admin_id


def test_la_10_refused_create_saves_nothing_and_can_be_retried(identity):
    client = signed_in(identity)
    create(client, "taken")
    operation = str(uuid.uuid4())
    assert create(client, "TAKEN", "developer", operation).status_code == 409
    assert client.get(f"/api/user-operations/{operation}").json() == {"status": "not_found"}
    assert create(client, "taken-two", "developer", operation).status_code == 201


def test_la_11_search_and_pages(identity):
    client = signed_in(identity)
    for number in range(30):
        create(client, f"team-{number:02d}")
    create(client, "someone-else")
    first = listed(client, "page=1&page_size=25")
    second = listed(client, "page=2&page_size=25")
    assert first["total"] == second["total"] == 32
    assert (len(first["users"]), first["has_more"]) == (25, True)
    assert (len(second["users"]), second["has_more"]) == (7, False)
    names = [row["username"] for row in first["users"] + second["users"]]
    assert len(set(names)) == 32
    found = listed(client, "search=TEAM-0&page_size=25")
    assert found["total"] == 10
    assert {row["username"] for row in found["users"]} == {f"team-0{n}" for n in range(10)}
    assert listed(client, "search=nobody")["users"] == []
    for query in ("page=0", "page_size=51", "page=x", "search=" + "x" * 81):
        assert client.get("/api/users?" + query).status_code == 400


def test_la_12_change_role_shows_the_new_role_and_applies_at_once(identity):
    admin = signed_in(identity)
    user_id = create(admin, "promoted").json()["id"]
    developer = signed_in(identity, "promoted", PASSWORD)
    assert developer.get("/api/users").status_code == 403

    response = change_role(admin, user_id, "admin")
    assert response.status_code == 200 and response.json()["role"] == "admin"
    assert listed(admin, "search=promoted")["users"][0]["role"] == "admin"
    assert developer.get("/api/users").status_code == 200

    assert change_role(admin, user_id, "developer").status_code == 200
    assert listed(admin, "search=promoted")["users"][0]["role"] == "developer"
    assert developer.get("/api/identity").status_code == 401
    assert change_role(admin, user_id, "owner").status_code == 400
    assert change_role(admin, str(uuid.uuid4()), "admin").status_code == 404
