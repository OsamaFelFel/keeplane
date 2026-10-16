"""Test-only token endpoint adapter around the actual Django personal-key service."""

import base64
import hashlib
import io
import json
import os
import secrets
import sys
import threading
import time
import uuid
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

STATE = Path("/state")
TRIAL = Path("/trial")
OBSERVED = {"provider": [], "exchange": [], "secrets": []}
REPORT = {"passed": False, "checks": [], "uid": os.geteuid()}


class Endpoint(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def answer(self, status, data):
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        raw = self.rfile.read(min(int(self.headers.get("Content-Length", "0")), 8193))
        if self.server.server_port == 18081:
            from django.db import close_old_connections

            close_old_connections()
            admitted = False
            try:
                form = parse_qs(raw.decode(), strict_parsing=True)
                assert secrets.compare_digest(
                    self.headers.get("X-Keeplane-Gateway-Credential", ""), CALLBACK
                )
                assert form["model_id"] == ["personal"]
                assert form["definition_fingerprint"] == [DEFINITION["digest"]]
                result = SERVICE.resolve(
                    form["subject_token"][0],
                    form["project_id"][0],
                    form["model_id"][0],
                    definition_fingerprint=form["definition_fingerprint"][0],
                )
                admitted = True
                self.answer(
                    200,
                    {
                        "access_token": result.for_provider(),
                        "token_type": "Bearer",
                        "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
                    },
                )
            except (
                Exception
            ):  # Deliberately generic: the adapter never returns service details.
                self.answer(400, {"error": "invalid_grant"})
            finally:
                OBSERVED["exchange"].append({"admitted": admitted})
                close_old_connections()
            return
        payload = json.loads(raw)
        credential = self.headers.get("Authorization", "").removeprefix("Bearer ")
        label = next(
            (
                name
                for name, value in KEYS.items()
                if secrets.compare_digest(value, credential)
            ),
            None,
        )
        OBSERVED["provider"].append(
            {
                "key_label": label,
                "inference": payload["messages"][0]["content"]
                == "personal-native-check",
                "credential_header_leak": any(
                    value in str(self.headers)
                    for value in OBSERVED["secrets"]
                    if value not in KEYS.values()
                ),
            }
        )
        self.answer(
            200 if label else 401,
            {
                "id": "fixture",
                "object": "chat.completion",
                "model": "synthetic",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )


def issue(identity, username):
    """Use actual CSRF login, consent and S256 code exchange; never seed tokens."""
    from django.test import Client

    client = Client(
        enforce_csrf_checks=True, HTTP_HOST="127.0.0.1:8090", HTTP_ORIGIN=ORIGIN
    )
    csrf = client.get("/api/auth-options").json()["csrf_token"]
    response = client.post(
        "/api/session",
        {"username": username, "password": PASSWORD},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert response.status_code == 200
    verifier = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    parameters = {
        "client_id": "keeplane-cli",
        "response_type": "code",
        "scope": "runtime",
        "redirect_uri": "http://127.0.0.1:62431/callback",
        "state": secrets.token_urlsafe(32),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    consent = client.get("/oauth/authorize/", parameters)
    assert consent.status_code == 200
    fields = {
        key: value
        for key, value in consent.context_data["form"].initial.items()
        if value is not None
    }
    fields["allow"] = "true"
    csrf = client.get("/api/auth-options").json()["csrf_token"]
    response = client.post(
        "/oauth/authorize/", urlencode(fields), content_type=FORM, HTTP_X_CSRFTOKEN=csrf
    )
    assert response.status_code == 302
    returned = parse_qs(urlsplit(response["Location"]).query)
    assert returned["state"] == [parameters["state"]] and returned["iss"] == [ORIGIN]
    token = Client(HTTP_HOST="127.0.0.1:8090").post(
        "/oauth/token/",
        urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": "keeplane-cli",
                "code": returned["code"][0],
                "code_verifier": verifier,
                "redirect_uri": parameters["redirect_uri"],
            }
        ),
        content_type=FORM,
    )
    assert token.status_code == 200
    value = token.json()
    assert identity.session(value["access_token"])["username"] == username
    OBSERVED["secrets"].extend((value["access_token"], value["refresh_token"]))
    return value["access_token"]


def check(name, token, project, *, key=None):
    before, exchanged = len(OBSERVED["provider"]), len(OBSERVED["exchange"])
    outgoing = Request(
        "http://127.0.0.1:5000/v1/chat/completions",
        data=json.dumps(
            {
                "model": "personal",
                "messages": [{"role": "user", "content": "personal-native-check"}],
                "max_tokens": 8,
            }
        ).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "X-Keeplane-Project-ID": project,
            "Content-Type": "application/json",
        },
    )
    try:
        response = urlopen(outgoing, timeout=8)
    except HTTPError as error:
        response = error
    with response:
        status, raw = (
            response.status,
            response.read(8192) + str(response.headers).encode(),
        )
    row = {
        "name": name,
        "status": status,
        "provider_contacts": len(OBSERVED["provider"]) - before,
        "exchange_contacts": len(OBSERVED["exchange"]) - exchanged,
        "client_secret_leak": any(
            value.encode() in raw for value in OBSERVED["secrets"]
        ),
    }
    REPORT["checks"].append(row)  # Preserve safe observations before assertions.
    assert row["exchange_contacts"] == 1 and not row["client_secret_leak"]
    assert row["provider_contacts"] == int(key is not None) and (status == 200) == (
        key is not None
    )
    if key:
        assert OBSERVED["provider"][-1] == {
            "key_label": key,
            "inference": True,
            "credential_header_leak": False,
        }


def main():
    global CALLBACK, DEFINITION, KEYS, SERVICE, ORIGIN, PASSWORD, FORM
    import django
    from importlib.metadata import version

    django.setup()
    REPORT["oauth_versions"] = {
        name: version(name)
        for name in (
            "certifi",
            "cffi",
            "charset-normalizer",
            "cryptography",
            "django-oauth-toolkit",
            "idna",
            "jwcrypto",
            "oauthlib",
            "pycparser",
            "requests",
            "typing_extensions",
            "urllib3",
        )
    }
    from accounts.cli_credentials import RuntimeIdentity
    from accounts.models import User
    from common.stores import stores
    from data_classes.models import ProjectClass
    from django.core.management import call_command
    from integrations.gateway.adapter import AgentgatewayModelAdapter
    from model_registry import personal_dispatch
    from model_registry.developer_keys import DjangoDeveloperKeyStore
    from model_registry.fingerprints import fingerprint
    from model_registry.key_validation import DjangoProviderKeyValidator
    from model_registry.models import DeveloperProviderKey, ModelApproval
    from model_registry.policy import DjangoModelPolicy
    from projects.access import organization_project_access
    from projects.services import DjangoProjectStore

    CALLBACK = (TRIAL / "callback-key").read_text()
    DEFINITION = json.loads((TRIAL / "definition.json").read_text())
    KEYS = {name: secrets.token_urlsafe(32) for name in ("a", "b", "next")}
    OBSERVED["secrets"] = [
        *KEYS.values(),
        *[
            path.read_text()
            for path in (
                TRIAL / "callback-key",
                TRIAL / "admin",
                TRIAL / "first-admin",
                TRIAL / "signing",
            )
        ],
    ]
    ORIGIN, PASSWORD, FORM = (
        "http://127.0.0.1:8090",
        secrets.token_urlsafe(24),
        "application/x-www-form-urlencoded",
    )
    for port in (18080, 18081):
        threading.Thread(
            target=ThreadingHTTPServer(("127.0.0.1", port), Endpoint).serve_forever,
            daemon=True,
        ).start()
    call_command(
        "migrate", interactive=False, stdout=io.StringIO(), stderr=io.StringIO()
    )
    _, native, _, classes = stores()
    identity = RuntimeIdentity(native)
    for name in ("a", "b"):
        native.create_user(
            {"username": "personal-" + name, "role": "developer", "password": PASSWORD}
        )
    call_command("register_cli_client", stdout=io.StringIO())
    tokens = {name: issue(identity, "personal-" + name) for name in ("a", "b")}
    owners = {
        name: User.objects.get(username="personal-" + name) for name in ("a", "b")
    }
    project = str(uuid.uuid4())
    DjangoProjectStore().register_use(
        str(owners["a"].pk), project, "Personal native trial"
    )
    classes.set_enabled(True)
    ProjectClass.objects.create(project_id=project, data_class_id="confidential")
    gateway = AgentgatewayModelAdapter(
        "http://127.0.0.1:4000", str(TRIAL / "admin"), str(TRIAL / "admin")
    )
    for _ in range(100):
        if gateway.models()[0] == 200:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("Native management not ready")
    status, _ = gateway.request(
        "/api/config/resources/llm.model",
        {"resources": [{"value": DEFINITION["value"]}]},
        method="PUT",
        timeout=5,
    )
    REPORT["registration_status"] = status
    assert status == 200
    status, body = gateway.resources()
    assert (
        status == 200
        and fingerprint("personal", body["resources"]) == DEFINITION["digest"]
    )
    for _ in range(100):
        status, active = gateway.models()
        if status == 200 and "personal" in {row["id"] for row in active["data"]}:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("Native personal model not active")
    ModelApproval.objects.create(
        model_id="personal",
        key_choice="personal",
        approved_classes=["Confidential"],
        gateway_fingerprint=DEFINITION["digest"],
    )
    # Fixture-only loopback allowance; the real validator still performs HTTP and binding checks.
    validator = partial(DjangoProviderKeyValidator, allow_loopback_http=True)
    personal_dispatch.DjangoProviderKeyValidator = validator
    key_root = STATE / "keys"
    key_stores = {
        name: DjangoDeveloperKeyStore(
            owner.pk, str(key_root), validate_key=validator(gateway)
        )
        for name, owner in owners.items()
    }
    for name in ("a", "b"):
        key_stores[name].put("personal", KEYS[name])
    REPORT["private_files"] = all(
        path.stat().st_uid == 65532 and path.stat().st_mode & 0o777 == 0o600
        for path in key_root.iterdir()
    )
    assert REPORT["private_files"] and key_root.stat().st_mode & 0o777 == 0o700
    SERVICE = personal_dispatch.DjangoPersonalDispatch(
        identity,
        DjangoModelPolicy(gateway),
        gateway,
        str(key_root),
        project_access=organization_project_access,
    )
    check("owner-a", tokens["a"], project, key="a")
    check("owner-b", tokens["b"], project, key="b")
    check("exchange-cache-disabled", tokens["a"], project, key="a")
    key_stores["a"].put("personal", KEYS["next"])
    check("next-call-replaced", tokens["a"], project, key="next")
    check("other-owner-unchanged", tokens["b"], project, key="b")
    key_stores["a"].remove("personal")
    check("next-call-removed", tokens["a"], project)
    check("other-owner-after-removal", tokens["b"], project, key="b")
    key_stores["a"].put("personal", KEYS["a"])
    identity.logout(tokens["a"])
    check("oauth-logout", tokens["a"], project)
    User.objects.filter(pk=owners["b"].pk).update(is_active=False)
    check("disabled-actor", tokens["b"], project)
    User.objects.filter(pk=owners["b"].pk).update(is_active=True)
    check("unknown-actor", secrets.token_urlsafe(32), project)
    check("unknown-project", tokens["b"], str(uuid.uuid4()))
    ProjectClass.objects.update(data_class_id="public")
    check("class-withdrawn", tokens["b"], project)
    ProjectClass.objects.update(data_class_id="confidential")
    row = DeveloperProviderKey.objects.get(owner=owners["b"], model_id="personal")
    DeveloperProviderKey.objects.filter(pk=row.pk).update(
        validation_fingerprint="b" * 64
    )
    check("stored-fingerprint-mismatch", tokens["b"], project)
    DeveloperProviderKey.objects.filter(pk=row.pk).update(
        validation_fingerprint=DEFINITION["digest"]
    )
    ModelApproval.objects.update(key_choice="shared")
    check("personal-choice-withdrawn", tokens["b"], project)
    ModelApproval.objects.update(key_choice="personal")
    path = key_root / row.key_name
    path.chmod(0o644)
    check("secret-unavailable", tokens["b"], project)
    path.chmod(0o600)
    check("recovered-private-secret", tokens["b"], project, key="b")
    REPORT["real_validation_contacts"] = sum(
        not item["inference"] for item in OBSERVED["provider"]
    )
    assert REPORT["real_validation_contacts"] == 4
    REPORT["passed"] = True


if __name__ == "__main__":
    if sys.argv[1:] == ["audit"]:
        needles = json.loads((STATE / "needles.json").read_text())
        ordinary = sys.stdin.buffer.read(2 * 1024 * 1024)
        print(
            json.dumps(
                {
                    "ordinary_logs_contain_secret": any(
                        value.encode() in ordinary for value in needles
                    )
                }
            )
        )
    else:
        try:
            main()
        except BaseException as error:
            REPORT["error_class"] = type(error).__name__
        finally:
            (STATE / "needles.json").write_text(json.dumps(OBSERVED["secrets"]))
            (STATE / "result.json").write_text(json.dumps(REPORT))
            (STATE / "done").touch()
        while True:
            time.sleep(60)
