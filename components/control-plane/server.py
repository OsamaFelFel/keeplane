"""Small Keeplane local preview: UI, model registration, and gateway calls."""

import json
import os
import sqlite3
import time
import uuid
from http.cookies import SimpleCookie
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from local_identity import IdentityError, LocalIdentity
from audit import AuditError, AuditStore
from data_classes import DataClassError, DataClassStore
from model_catalog import ModelCatalog, fingerprint
from provider_keys import (save as save_provider_key, remove as remove_provider_key,
                           from_resource as provider_key_file, is_managed as managed_provider_key)


GATEWAY = os.environ.get("GATEWAY_URL", "http://gateway:4000")
UI = Path("/ui")
MAX_BODY = 64 * 1024
TRIAL_KEY = os.environ.get("PREVIEW_PROVIDER_KEY", "")
RUNNER_URLS = {url.strip().rstrip("/") for url in
               os.environ.get("PREVIEW_RUNNER_URLS", "http://qwen:8080").split(",") if url.strip()}


class NoRunnerRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


RUNNER_OPENER = build_opener(NoRunnerRedirect)
AUDIT = AuditStore(os.environ["MODEL_APPROVAL_DB"]) \
    if os.environ.get("ACCOUNT_DB") and os.environ.get("MODEL_APPROVAL_DB") else None
IDENTITY = LocalIdentity(os.environ["ACCOUNT_DB"], os.environ["FIRST_ADMIN_PASSWORD_FILE"], AUDIT) \
    if os.environ.get("ACCOUNT_DB") else None
CATALOG = ModelCatalog(os.environ["MODEL_APPROVAL_DB"], AUDIT) if AUDIT else None
DATA_CLASSES = DataClassStore(os.environ["MODEL_APPROVAL_DB"], AUDIT) if AUDIT else None
GATEWAY_FILE_CONFIG = os.environ.get("GATEWAY_FILE_CONFIG")
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "")
PUBLIC_ORIGIN_ALIASES = {origin.strip() for origin in
                         os.environ.get("PUBLIC_ORIGIN_ALIASES", "").split(",") if origin.strip()}
PROVIDER_KEY_DIR = os.environ.get("PROVIDER_KEY_DIR", "")
CLOUD_BASE_URLS = {"openai": os.environ.get("PREVIEW_OPENAI_BASE_URL", ""),
                   "anthropic": os.environ.get("PREVIEW_ANTHROPIC_BASE_URL", "")}


def model_fingerprint(model_id, resources):
    return fingerprint(model_id, resources, GATEWAY_FILE_CONFIG)


def local_runner(address, model=None):
    """Inspect an explicitly allowed runner; the preview has no admin login."""
    address = address.rstrip("/") if isinstance(address, str) else ""
    if address not in RUNNER_URLS:
        return 400, {"error": "This runner address is not enabled in the local preview"}
    try:
        with RUNNER_OPENER.open(address + "/v1/models", timeout=10) as response:
            listing = json.load(response)
        if not isinstance(listing, dict) or not isinstance(listing.get("data"), list):
            raise ValueError("Invalid model list")
        served = listing["data"]
        names = [item.get("id") for item in served if isinstance(item, dict) and isinstance(item.get("id"), str)]
        if model is None:
            runtime = {}
            # llama.cpp exposes the loaded instance's effective context in
            # /props. Its model metadata reports a different training limit.
            # Only attribute the instance setting when it serves one model.
            if len(names) == 1:
                try:
                    with RUNNER_OPENER.open(address + "/props", timeout=2) as response:
                        props = json.load(response)
                    active = props.get("default_generation_settings", {}).get("n_ctx")
                    if type(active) is int and active > 0:
                        runtime[names[0]] = {"active_context_tokens": active}
                        matching = next(item for item in served if isinstance(item, dict)
                                        and item.get("id") == names[0])
                        metadata = matching.get("meta", {})
                        training = metadata.get("n_ctx_train") if isinstance(metadata, dict) else None
                        if type(training) is int and training > 0:
                            runtime[names[0]]["training_context_tokens"] = training
                except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError,
                        AttributeError, TypeError):
                    pass  # Discovery still works for runners without /props.
            return 200, {"models": names, "runtime": runtime}
        if model not in names:
            return 400, {"error": f"{model} is not served by the runner at {address}"}
        probe = Request(address + "/v1/chat/completions", method="POST",
                        data=json.dumps({"model": model, "messages": [{"role": "user", "content": "Reply OK."}],
                                         "max_tokens": 1}).encode(),
                        headers={"Content-Type": "application/json"})
        with RUNNER_OPENER.open(probe, timeout=30) as response:
            checked = json.load(response)
        if not isinstance(checked, dict) or not isinstance(checked.get("choices"), list) or not checked["choices"]:
            raise ValueError("No completion choice")
        choice = checked["choices"][0]
        if not isinstance(choice, dict):
            raise ValueError("Invalid completion choice")
        message = choice.get("message", {})
        if not isinstance(message, dict) or not isinstance(message.get("content"), str) or not message["content"].strip():
            raise ValueError("No model answer")
        return 200, {"models": names}
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return 503, {"error": f"The runner at {address} didn't answer."}


def gateway(path, body=None, method=None, connection_retries=0, timeout=120):
    payload = None if body is None else json.dumps(body).encode()
    request = Request(GATEWAY + path, data=payload, method=method or ("POST" if payload is not None else "GET"))
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"error": raw or f"Gateway returned HTTP {error.code}"}
    except URLError as error:
        # A refused TCP connection means the request never reached a gateway.
        # This can occur briefly while Kubernetes removes a failed pod endpoint.
        if connection_retries and isinstance(error.reason, ConnectionRefusedError):
            time.sleep(0.25)
            return gateway(path, body, method, connection_retries - 1, timeout)
        return 503, {"error": "Gateway unavailable", "detail": str(error)}
    except TimeoutError as error:
        return 503, {"error": "Gateway unavailable", "detail": str(error)}


def gateway_model_resources():
    # A gateway replica can return a transient 500 from the read-only
    # management endpoint while its model store reconnects. Never retry PUT.
    for attempt in range(3):
        status, result = gateway("/api/config/resources/llm.model", timeout=10)
        if status < 500 or attempt == 2:
            return status, result
        time.sleep(0.25)


def model_details(model_id, resources):
    # The fixture in local.yaml is file-owned and absent from the resource API.
    if model_id == "local-fixture":
        return {"id": model_id, "provider": "Test fixture", "kind": "fixture",
                "upstream_model": "mock-local"}

    resource = resources.get(model_id, {})
    params = resource.get("params", {})
    provider = resource.get("provider")
    if provider in ("openAI", "anthropic"):
        return {"id": model_id, "provider": "OpenAI" if provider == "openAI" else "Anthropic",
                "kind": "cloud", "upstream_model": params.get("model")}
    source = params.get("baseUrl")
    if source == "http://qwen:8080/v1":
        return {"id": model_id, "provider": "Qwen Coder via llama.cpp", "kind": "real-local",
                "upstream_model": params.get("model")}
    if source == "http://guarded-provider:18081/v1":
        return {"id": model_id, "provider": "Guarded endpoint trial (Qwen)", "kind": "endpoint-trial",
                "upstream_model": params.get("model")}
    if source == "http://model:18080/v1":
        return {"id": model_id, "provider": "Test fixture", "kind": "fixture",
                "upstream_model": params.get("model")}
    if isinstance(source, str) and source.endswith("/v1") and source[:-3] in RUNNER_URLS:
        return {"id": model_id, "provider": "Local runner", "kind": "real-local",
                "upstream_model": params.get("model")}
    return {"id": model_id, "provider": "Unknown source", "kind": "unknown",
            "upstream_model": params.get("model")}


def effective_approval_ids():
    status, listing = gateway("/v1/models", timeout=10)
    if status != 200:
        return status, listing, None
    status, resources = gateway_model_resources()
    if status != 200:
        return status, resources, None
    raw_resources = resources.get("resources", [])
    active = set()
    for item in listing.get("data", []):
        model_id = item.get("id")
        approval = CATALOG.get(model_id) if model_id else None
        if approval and approval["gateway_fingerprint"] == model_fingerprint(model_id, raw_resources):
            active.add(model_id)
    return 200, {}, active


def confirm_new_model(model_id, expected_params):
    """Wait for management readback, then ask through the registered gateway path."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status, listing = gateway("/v1/models", timeout=5)
        resource_status, resources = gateway("/api/config/resources/llm.model", timeout=5)
        if status == 200 and resource_status == 200:
            raw = resources.get("resources", [])
            entry = next((item.get("value", {}) for item in raw if item.get("id") == model_id), {})
            if model_id in {item.get("id") for item in listing.get("data", [])} and \
                    entry.get("params") == expected_params:
                model_revision = model_fingerprint(model_id, raw)
                if model_revision:
                    for delay in (0, 0.2, 0.4, 0.8, 1.6):
                        if delay:
                            time.sleep(delay)
                        answer_status, answer = gateway("/v1/chat/completions", {
                            "model": model_id, "messages": [{"role": "user", "content": "Reply OK."}],
                            "max_tokens": 1}, timeout=30, connection_retries=3)
                        if answer_status == 200 and answer.get("choices") and \
                                answer["choices"][0].get("message", {}).get("content"):
                            return model_revision
                        # A different replica may not have applied the registration yet.
                        # Only this explicit not-found response is safe to retry.
                        if answer_status != 404 or not isinstance(answer.get("error"), dict) or \
                                answer["error"].get("code") != "model_not_found":
                            break
                    return None
        if time.monotonic() < deadline:
            time.sleep(0.3)
    return None


def undo_new_model(model_id, expected_params):
    """Remove only the model definition this request created when it can be verified."""
    status, resources = gateway("/api/config/resources/llm.model", timeout=5)
    if status != 200:
        return False
    entry = next((item.get("value", {}) for item in resources.get("resources", [])
                  if item.get("id") == model_id), {})
    if entry.get("params") != expected_params:
        return False
    status, _ = gateway("/api/config/resources/llm.model/" + model_id, method="DELETE")
    return status == 200


def undo_cloud_model(model_id, expected_resource):
    """Remove a failed cloud registration only if its complete definition is unchanged."""
    status, resources = gateway_model_resources()
    if status != 200:
        return False
    entry = next((item.get("value", {}) for item in resources.get("resources", [])
                  if item.get("id") == model_id), {})
    if not entry:
        return True
    if entry != expected_resource:
        return False
    status, _ = gateway("/api/config/resources/llm.model/" + model_id, method="DELETE")
    return status == 200


def confirm_cloud_model(model_id, expected_resource, retry_refused=False):
    """Verify management readback and one answer through the chosen gateway."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status, listing = gateway("/v1/models", timeout=5)
        resource_status, resources = gateway_model_resources()
        if status == 200 and resource_status == 200:
            raw = resources.get("resources", [])
            entry = next((item.get("value", {}) for item in raw if item.get("id") == model_id), {})
            if model_id in {item.get("id") for item in listing.get("data", [])} and \
                    entry == expected_resource:
                revision = model_fingerprint(model_id, raw)
                if not revision:
                    return None, "The gateway didn't register it."
                for delay in (0, 0.2, 0.4, 0.8, 1.6, 3.2):
                    if delay:
                        time.sleep(delay)
                    answer_status, answer = gateway("/v1/chat/completions", {
                        "model": model_id,
                        "messages": [{"role": "user", "content": "Reply OK."}],
                        "max_tokens": 1}, timeout=30, connection_retries=3)
                    if answer_status == 200 and answer.get("choices") and \
                            answer["choices"][0].get("message", {}).get("content"):
                        return revision, None
                    if answer_status in (401, 403):
                        if retry_refused and delay != 3.2:
                            continue
                        return None, "The provider refused the key."
                    if answer_status == 404 and isinstance(answer.get("error"), dict) and \
                            answer["error"].get("code") == "model_not_found":
                        continue
                    return None, "The provider didn't answer."
                return None, "The gateway didn't register it."
        time.sleep(0.3)
    return None, "The gateway didn't register it."


class Handler(BaseHTTPRequestHandler):
    def replace_shared_key(self, model_id, resource, previous, classes, replacement):
        if not previous["owned_by_keeplane"] or resource.get("provider") not in ("openAI", "anthropic"):
            return self.reply(400, {"error": "This trial can replace keys only for cloud models Keeplane added"})
        old_path = provider_key_file(resource)
        if not managed_provider_key(PROVIDER_KEY_DIR, old_path):
            return self.reply(400, {"error": "This model's shared key is not managed by Keeplane"})
        try:
            new_path = save_provider_key(PROVIDER_KEY_DIR, replacement)
        except OSError:
            return self.reply(503, {"error": "Shared provider key storage is unavailable"})
        updated = json.loads(json.dumps(resource))
        updated["auth"]["key"]["value"] = {"file": new_path}
        resource_path = "/api/config/resources/llm.model/" + model_id
        check_name = "keeplane-keycheck-" + uuid.uuid4().hex
        check_resource = json.loads(json.dumps(updated))
        check_resource["name"] = check_name

        # A model already in service may still answer with its old route just
        # after a management update. A unique model proves the new key first.
        check_status, _ = gateway("/api/config/resources/llm.model",
                                  {"resources": [{"value": check_resource}]}, "PUT")
        checked, _ = confirm_cloud_model(check_name, check_resource) if check_status == 200 else (None, None)
        check_removed = undo_cloud_model(check_name, check_resource)
        if checked is None or not check_removed:
            if check_removed:
                remove_provider_key(PROVIDER_KEY_DIR, new_path)
            return self.reply(503, {"error": "The replacement key didn't answer through the gateway. " +
                              ("The previous key is still active." if check_removed else
                               "A verification model may need cleanup; check Models.")})

        def restore_previous():
            status, resources = gateway_model_resources()
            if status != 200:
                return False
            current = next((item.get("value", {}) for item in resources.get("resources", [])
                            if item.get("id") == model_id), {})
            if current == updated:
                status, _ = gateway(resource_path, {"value": resource}, "PUT")
                if status != 200:
                    return False
            elif current != resource:
                return False
            revision, _ = confirm_cloud_model(model_id, resource, retry_refused=True)
            if revision is None:
                return False
            try:
                CATALOG.approve(model_id, previous["approved_classes"], revision, self.actor(),
                                owned_by_keeplane=True, key_choice="shared")
            except (ValueError, IdentityError, sqlite3.Error):
                return False
            return remove_provider_key(PROVIDER_KEY_DIR, new_path)

        status, _ = gateway(resource_path, {"value": updated}, "PUT")
        revision, _ = confirm_cloud_model(model_id, updated, retry_refused=True) if status == 200 else (None, None)
        if revision is None:
            restored = restore_previous()
            return self.reply(503, {"error": "The replacement key didn't work. " +
                              ("The previous key is still active." if restored else
                               "The model may need admin attention; check Models.")})
        try:
            approval = CATALOG.approve(model_id, classes, revision, self.actor(),
                                       owned_by_keeplane=True, key_choice="shared")
        except (ValueError, IdentityError, sqlite3.Error):
            restored = restore_previous()
            return self.reply(503, {"error": "Keeplane couldn't save the change. " +
                              ("The previous key is still active." if restored else
                               "The model may need admin attention; check Models.")})
        if not remove_provider_key(PROVIDER_KEY_DIR, old_path):
            return self.reply(503, {"error": "New key saved, but the previous key file needs cleanup"})
        return self.reply(200, approval)

    def add_cloud_model(self, body, name, model, classes):
        if not CATALOG or not IDENTITY:
            return self.reply(403, {"error": "Sign in as an admin to add a cloud model"})
        source = body.get("source")
        provider = {"openai": "openAI", "anthropic": "anthropic"}[source]
        key_choice = body.get("key_choice")
        if key_choice not in ("shared", "none"):
            return self.reply(400, {"error": "Choose a supported provider key option"})
        if key_choice == "shared":
            shared_key = body.get("shared_key")
            if not isinstance(shared_key, str) or not 12 <= len(shared_key) <= 512 or \
                    "\n" in shared_key or "\r" in shared_key:
                return self.reply(400, {"error": "Enter a valid shared provider key"})

        status, listing = gateway("/v1/models", timeout=10)
        if status != 200:
            return self.reply(status, listing)
        resource_status, resources = gateway_model_resources()
        if resource_status != 200:
            return self.reply(resource_status, resources)
        if name in {item.get("id") for item in listing.get("data", [])} or any(
            item.get("value", {}).get("provider") == provider and
            item.get("value", {}).get("params", {}).get("model") == model
            for item in resources.get("resources", [])):
            label = "OpenAI" if source == "openai" else "Anthropic"
            return self.reply(409, {"error": f"{model} from {label} is already added."})

        key_path = None
        if key_choice == "shared":
            try:
                key_path = save_provider_key(PROVIDER_KEY_DIR, shared_key)
            except OSError:
                return self.reply(503, {"error": "Shared provider key storage is unavailable"})
        params = {"model": model}
        if CLOUD_BASE_URLS[source]:
            params["baseUrl"] = CLOUD_BASE_URLS[source]
        resource = {"name": name, "provider": provider, "params": params}
        if key_path:
            resource["auth"] = {"key": {"value": {"file": key_path}}}
        status, _ = gateway("/api/config/resources/llm.model",
                            {"resources": [{"value": resource}]}, "PUT")
        if status != 200:
            removed = undo_cloud_model(name, resource)
            if key_path and removed:
                remove_provider_key(PROVIDER_KEY_DIR, key_path)
            return self.reply(503, {"error": "The gateway didn't confirm registration. " +
                              ("Nothing was saved." if removed else
                               "Its entry may remain without approval; check Models.")})
        revision, reason = confirm_cloud_model(name, resource)
        if revision is None:
            removed = undo_cloud_model(name, resource)
            if key_path and removed:
                remove_provider_key(PROVIDER_KEY_DIR, key_path)
            suffix = " Nothing was saved." if removed else \
                " Its gateway entry may remain without a working key; check Models."
            if reason == "The provider refused the key.":
                reason = f"{'OpenAI' if source == 'openai' else 'Anthropic'} refused the key."
            elif reason == "The provider didn't answer.":
                reason = f"{'OpenAI' if source == 'openai' else 'Anthropic'} didn't answer."
            return self.reply(503, {"error": reason + suffix})
        try:
            approval = CATALOG.approve(name, classes, revision, self.actor(),
                                       owned_by_keeplane=True, key_choice=key_choice)
        except (ValueError, IdentityError, sqlite3.Error):
            removed = undo_cloud_model(name, resource)
            if key_path and removed:
                remove_provider_key(PROVIDER_KEY_DIR, key_path)
            return self.reply(503, {"error": "Keeplane couldn't save model approval. " +
                              ("Registration was removed." if removed else
                               "The model may remain in the gateway without Keeplane approval.")})
        return self.reply(200, {"name": name, "key_choice": approval["key_choice"],
                                "approved_classes": approval["approved_classes"]})

    def actor(self):
        return self._signed_in_user["id"], self._signed_in_user["username"]

    def session_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return cookie["keeplane_session"].value if "keeplane_session" in cookie else ""
        except Exception:
            return ""

    def require_admin(self, path):
        if not IDENTITY:
            return True
        self._signed_in_user = IDENTITY.session(self.session_token())
        if self._signed_in_user and self._signed_in_user["role"] == "admin":
            return True
        if path.startswith("/api/"):
            self.reply(403 if self._signed_in_user else 401,
                       {"error": "Admin access required" if self._signed_in_user else "Sign in to Keeplane"})
        else:
            self.send_response(302)
            self.send_header("Location", "/sign-in")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        return False

    def session_cookie(self, token, max_age):
        cookie = SimpleCookie()
        cookie["keeplane_session"] = token
        cookie["keeplane_session"]["path"] = "/"
        cookie["keeplane_session"]["httponly"] = True
        cookie["keeplane_session"]["samesite"] = "Strict"
        cookie["keeplane_session"]["max-age"] = max_age
        if PUBLIC_ORIGIN.startswith("https://"):
            cookie["keeplane_session"]["secure"] = True
        return cookie.output(header="").strip()

    def identity_action_allowed(self):
        if self.headers.get("X-Keeplane-Action") != "1" or \
                self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json" or \
                not self.trusted_origin():
            self.reply(403, {"error": "Changes require Keeplane's admin UI"})
            return False
        return True

    def trusted_origin(self):
        origin = self.headers.get("Origin")
        return not origin or origin in {PUBLIC_ORIGIN, *PUBLIC_ORIGIN_ALIASES}

    def identity_result(self, action):
        try:
            status, result = action()
            self.reply(status, result)
        except (IdentityError, DataClassError, AuditError) as error:
            self.reply(error.status, {"error": error.message})
        except sqlite3.Error:
            self.reply(503, {"error": "Keeplane settings storage is unavailable"})

    def reply(self, status, body, content_type="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def incoming(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > MAX_BODY:
                raise ValueError("Request body must be between 1 byte and 64 KB")
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object")
            return value
        except (ValueError, json.JSONDecodeError) as error:
            self.reply(400, {"error": str(error)})
            return None

    def do_GET(self):
        route = urlsplit(self.path)
        query = parse_qs(route.query)
        path = route.path
        if IDENTITY:
            if path == "/api/auth-options":
                return self.reply(200, {"sso_connected": False})
            if path == "/api/identity":
                signed_in = IDENTITY.session(self.session_token())
                return self.reply(200, signed_in) if signed_in else self.reply(401, {"error": "Sign in to Keeplane"})
            if path == "/sign-in":
                return self.reply(200, (UI / "sign-in.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/sign-out":
                IDENTITY.logout(self.session_token())
                self.send_response(302)
                self.send_header("Location", "/sign-in")
                self.send_header("Set-Cookie", self.session_cookie("", 0))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if path == "/" and (IDENTITY.session(self.session_token()) or {}).get("role") == "developer":
                self.send_response(302)
                self.send_header("Location", "/app/")
                self.end_headers()
                return
            if path not in ("/health/app", "/style.css", "/sign-in.js", "/app", "/app/", "/app/data-classes", "/app/audit") \
                    and not path.startswith(("/fonts/", "/app/assets/")) \
                    and not self.require_admin(path):
                return
        if IDENTITY and path.startswith("/api/user-operations/"):
            operation_id = path.removeprefix("/api/user-operations/")
            return self.identity_result(lambda: (200, IDENTITY.user_operation(
                operation_id, self.actor()[0])))
        if DATA_CLASSES and path == "/api/data-classes":
            try:
                if not DATA_CLASSES.enabled():
                    return self.reply(200, {"enabled": False, "classes": []})
                status, result, effective = effective_approval_ids()
                return self.reply(status, {"enabled": True, "classes": DATA_CLASSES.list(effective)} if status == 200 else result)
            except sqlite3.Error:
                return self.reply(503, {"error": "Keeplane settings storage is unavailable"})
        if AUDIT and path == "/api/audit/options":
            return self.identity_result(lambda: (200, {"options": AUDIT.options()}))
        if AUDIT and path == "/api/audit/records":
            try:
                page = int(query.get("page", ["1"])[0])
                return self.identity_result(lambda: (200, AUDIT.records(
                    query.get("kind", ["all"])[0], query.get("search", [""])[0], page)))
            except ValueError:
                return self.reply(400, {"error": "Page must be a number"})
        if IDENTITY and path == "/api/users":
            return self.identity_result(lambda: (200, IDENTITY.users(query)))
        if IDENTITY and path == "/api/edition-note":
            return self.identity_result(lambda: (200, IDENTITY.edition_note(self.actor()[0])))
        if self.path == "/health/app":
            # Keep the admin UI in service while its gateway is unavailable.
            self.reply(200, {"app": "ready"})
        elif self.path == "/health":
            status, _ = gateway("/api/runtime")
            self.reply(200 if status == 200 else 503, {"gateway": "ready" if status == 200 else "unavailable"})
        elif self.path == "/api/status":
            status, result = gateway("/api/runtime")
            if status == 200:
                self.reply(200, {"gateway": {"name": "agentgateway",
                                             "version": result.get("build", {}).get("version", "unknown")}})
            else:
                self.reply(status, result)
        elif self.path == "/api/models":
            status, result = gateway("/v1/models", timeout=10)
            if status != 200:
                return self.reply(status, result)
            resource_status, resource_result = gateway_model_resources()
            if resource_status != 200:
                return self.reply(resource_status, resource_result)
            raw_resources = resource_result.get("resources", [])
            resources = {item["id"]: item.get("value", {})
                         for item in raw_resources if "id" in item}
            models = []
            for item in result.get("data", []):
                if "id" not in item:
                    continue
                details = model_details(item["id"], resources)
                if CATALOG:
                    approval = CATALOG.get(item["id"])
                    if approval and approval["gateway_fingerprint"] != model_fingerprint(item["id"], raw_resources):
                        approval = None
                    details.update({"approved": approval is not None,
                                    "key_choice": approval["key_choice"] if approval else None,
                                    "approved_classes": approval["approved_classes"] if approval else [],
                                    "owned_by_keeplane": approval["owned_by_keeplane"] if approval else False})
                models.append(details)
            self.reply(200, {"models": models})
        elif IDENTITY and path == "/users":
            self.send_response(302)
            self.send_header("Location", "/app/")
            self.end_headers()
        elif IDENTITY and path == "/data-classes":
            self.send_response(302)
            self.send_header("Location", "/app/data-classes")
            self.end_headers()
        elif IDENTITY and path == "/audit":
            self.send_response(302)
            self.send_header("Location", "/app/audit")
            self.end_headers()
        elif IDENTITY and path in ("/editions", "/editions.js"):
            name = {"/editions": "editions.html", "/editions.js": "editions.js"}[path]
            content_type = "text/javascript" if name.endswith(".js") else "text/html"
            self.reply(200, (UI / name).read_bytes(), content_type + "; charset=utf-8")
        elif path in ("/app", "/app/", "/app/data-classes", "/app/audit"):
            index = UI / "web/dist/index.html"
            self.reply(200, index.read_bytes(), "text/html; charset=utf-8") if index.is_file() else \
                self.reply(503, {"error": "Admin UI build is unavailable"})
        elif path.startswith("/app/assets/"):
            name = path.removeprefix("/app/assets/")
            asset = UI / "web/dist/assets" / name
            if not name or "/" in name or ".." in name or not asset.is_file():
                return self.reply(404, {"error": "Not found"})
            media_type = "text/css" if name.endswith(".css") else \
                "text/javascript" if name.endswith(".js") else \
                "image/svg+xml" if name.endswith(".svg") else "application/octet-stream"
            self.reply(200, asset.read_bytes(), media_type)
        elif self.path in ("/", "/style.css", "/app.js", "/sign-in.js"):
            name = "index.html" if self.path == "/" else self.path[1:]
            content_type = {"index.html": "text/html", "style.css": "text/css",
                            "app.js": "text/javascript", "sign-in.js": "text/javascript"}[name]
            self.reply(200, (UI / name).read_bytes(), content_type + "; charset=utf-8")
        elif self.path in ("/fonts/IBMPlexSans-Regular.woff2", "/fonts/IBMPlexSans-SemiBold.woff2",
                           "/fonts/IBMPlexMono-Regular.woff2"):
            self.reply(200, (UI / self.path[1:]).read_bytes(), "font/woff2")
        else:
            self.reply(404, {"error": "Not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if IDENTITY and path == "/api/session":
            if not self.trusted_origin():
                return self.reply(403, {"error": "Sign in from Keeplane's page"})
            body = self.incoming()
            if body is None:
                return
            try:
                token = IDENTITY.login(body.get("username"), body.get("password"))
            except IdentityError as error:
                return self.reply(error.status, {"error": error.message})
            return self.reply(200, {"signed_in": True},
                              headers={"Set-Cookie": self.session_cookie(token, 8 * 60 * 60)})
        if IDENTITY and not self.require_admin(path):
            return
        body = self.incoming()
        if body is None:
            return
        if IDENTITY and path == "/api/edition-note/consume":
            if not self.identity_action_allowed():
                return
            return self.identity_result(lambda: (200, IDENTITY.consume_edition_note(self.actor()[0])))
        segments = urlsplit(self.path).path.strip("/").split("/")
        if CATALOG and len(segments) == 4 and segments[:2] == ["api", "models"] and segments[3] == "setup":
            if not self.identity_action_allowed():
                return
            model_id = unquote(segments[2])
            choice = body.get("key_choice")
            previous = CATALOG.get(model_id)
            if choice not in ("none", "shared") or (choice == "shared" and
                                                      (not previous or previous["key_choice"] != "shared")):
                return self.reply(400, {"error": "Choose a supported provider key option"})
            replacement = body.get("replace_shared_key", "")
            if not isinstance(replacement, str) or (replacement and
                    (choice != "shared" or not 12 <= len(replacement) <= 512 or
                     "\n" in replacement or "\r" in replacement)):
                return self.reply(400, {"error": "Enter a valid replacement shared key"})
            try:
                classes_on = DATA_CLASSES.enabled()
                # Editing a key while classes are off must not erase approvals
                # that will apply if the admin turns the mode on again.
                classes = body.get("approved_classes", []) if classes_on else \
                    (previous["approved_classes"] if previous else [])
                # Validate before making a model call or changing storage.
                known_classes = {item["name"] for item in DATA_CLASSES.list()}
                if not isinstance(classes, list) or \
                        any(not isinstance(item, str) or item not in known_classes for item in classes) or \
                        len(classes) != len(set(classes)):
                    raise ValueError("Choose valid data classes")
            except ValueError as error:
                return self.reply(400, {"error": str(error)})
            except sqlite3.Error:
                return self.reply(503, {"error": "Keeplane settings storage is unavailable"})
            status, listing = gateway("/v1/models", timeout=10)
            if status != 200:
                return self.reply(status, listing)
            if model_id not in {item.get("id") for item in listing.get("data", [])}:
                return self.reply(404, {"error": "Model not found in the gateway"})
            resource_status, resource_result = gateway_model_resources()
            if resource_status != 200:
                return self.reply(resource_status, resource_result)
            raw_resources = resource_result.get("resources", [])
            resource = next((item.get("value", {}) for item in raw_resources
                             if item.get("id") == model_id), {})
            if choice == "none" and resource.get("auth"):
                return self.reply(400, {"error": "This model has a provider key in the gateway"})
            if choice == "shared" and not managed_provider_key(
                    PROVIDER_KEY_DIR, provider_key_file(resource)):
                return self.reply(400, {"error": "This model's shared key is not managed by Keeplane"})
            current_fingerprint = model_fingerprint(model_id, raw_resources)
            if not current_fingerprint:
                return self.reply(503, {"error": "The gateway model definition could not be verified"})
            if choice == "shared" and previous["gateway_fingerprint"] != current_fingerprint:
                return self.reply(409, {"error": "This model changed in the gateway and must be set up again"})
            if replacement:
                return self.replace_shared_key(model_id, resource, previous, classes, replacement)
            answer_status, answer = gateway("/v1/chat/completions", {
                "model": model_id, "messages": [{"role": "user", "content": "Reply OK."}],
                "max_tokens": 1}, timeout=30)
            if answer_status != 200 or not answer.get("choices"):
                return self.reply(503, {"error": "The model didn't answer. Nothing was saved."})
            try:
                # A definition replaced outside Keeplane loses its provenance.
                still_owned = bool(previous and previous["owned_by_keeplane"] and
                                   previous["gateway_fingerprint"] == current_fingerprint)
                return self.reply(200, CATALOG.approve(model_id, classes, current_fingerprint,
                                                       self.actor(), owned_by_keeplane=still_owned,
                                                       key_choice=choice))
            except ValueError as error:
                return self.reply(400, {"error": str(error)})
            except IdentityError as error:
                return self.reply(error.status, {"error": error.message})
            except sqlite3.Error:
                return self.reply(503, {"error": "Keeplane settings storage is unavailable"})
        if IDENTITY and self.path == "/api/users":
            if self.identity_action_allowed():
                return self.identity_result(lambda: (201, IDENTITY.create_user(body, self.actor()[0])))
            return
        if DATA_CLASSES and self.path == "/api/data-classes":
            if self.identity_action_allowed():
                effective = set()
                if body.get("approved_model_ids"):
                    status, result, effective = effective_approval_ids()
                    if status != 200:
                        return self.reply(status, result)
                return self.identity_result(lambda: (201, DATA_CLASSES.add(body, effective, self.actor())))
            return
        if self.path == "/api/runners/models":
            status, result = local_runner(body.get("address"))
            return self.reply(status, result)
        if self.path == "/api/models":
            if IDENTITY and not self.identity_action_allowed():
                return
            name = body.get("name", "")
            model = body.get("model", "")
            source = body.get("source", "fixture")
            if not isinstance(name, str) or not name or len(name) > 80 or not all(c.isalnum() or c in "-_.:" for c in name):
                return self.reply(400, {"error": "Model name must use letters, numbers, dots, dashes, underscores or colons"})
            if not isinstance(model, str) or not model or len(model) > 100:
                return self.reply(400, {"error": "Enter an upstream model ID"})
            try:
                classes = (body.get("approved_classes", []) if DATA_CLASSES.enabled() else []) if CATALOG else None
                if classes is not None:
                    known_classes = {item["name"] for item in DATA_CLASSES.list()}
            except sqlite3.Error:
                return self.reply(503, {"error": "Keeplane settings storage is unavailable"})
            if classes is not None:
                if not isinstance(classes, list) or \
                        any(not isinstance(item, str) or item not in known_classes for item in classes) or \
                        len(classes) != len(set(classes)):
                    return self.reply(400, {"error": "Choose valid data classes"})
            if source in CLOUD_BASE_URLS:
                return self.add_cloud_model(body, name, model, classes)
            sources = {"fixture": "http://model:18080/v1", "qwen": "http://qwen:8080/v1",
                       "guarded": "http://guarded-provider:18081/v1"}
            if source == "runner":
                address = body.get("address", "")
                checked_status, checked = local_runner(address, model)
                if checked_status != 200:
                    return self.reply(checked_status, checked)
                sources["runner"] = address.rstrip("/") + "/v1"
            if source not in sources:
                return self.reply(400, {"error": "Choose a supported local source"})
            if source in ("qwen", "guarded"):
                try:
                    with urlopen("http://qwen:8080/health", timeout=10) as response:
                        if response.status != 200:
                            raise URLError("Qwen is still loading")
                except (HTTPError, URLError, TimeoutError):
                    return self.reply(503, {"error": "The local Qwen runner is not ready"})
            if source == "guarded":
                if not TRIAL_KEY:
                    return self.reply(503, {"error": "The disposable test key is not configured"})
                try:
                    with urlopen("http://guarded-provider:18081/health", timeout=2) as response:
                        if response.status != 200:
                            raise URLError("Guarded endpoint is still loading")
                except (HTTPError, URLError, TimeoutError):
                    return self.reply(503, {"error": "The guarded endpoint is not ready"})
            listed_status, listed = gateway("/v1/models", timeout=10)
            if listed_status != 200:
                return self.reply(listed_status, listed)
            if name in {item.get("id") for item in listed.get("data", [])}:
                resource_status, resource_result = gateway_model_resources()
                if resource_status != 200:
                    return self.reply(resource_status, resource_result)
                existing = next((item.get("value", {})
                                 for item in resource_result.get("resources", []) if item.get("id") == name), None)
                if name == "local-fixture":
                    existing = {"params": {"model": "mock-local", "baseUrl": sources["fixture"]}}
                expected_auth = {"key": {"value": TRIAL_KEY}} if source == "guarded" else None
                if existing and existing.get("params") == {"model": model, "baseUrl": sources[source]} \
                        and (source != "guarded" or existing.get("auth") == expected_auth):
                    return self.reply(200, {"name": name, "existing": True})
                return self.reply(409, {"error": "A model with this name is already registered"})
            # External endpoints and credentials need account and policy controls.
            resource = {"name": name, "provider": {"custom": {"formats": [{"type": "completions"}]}},
                        "params": {"model": model, "baseUrl": sources[source]}}
            if source == "guarded":
                resource["auth"] = {"key": {"value": TRIAL_KEY}}
            status, result = gateway("/api/config/resources/llm.model", {"resources": [{"value": resource}]}, "PUT")
            if status != 200:
                if classes is not None:
                    if undo_new_model(name, resource["params"]):
                        return self.reply(503, {"error": "The gateway did not confirm registration. A matching definition was removed."})
                    if status >= 500:
                        return self.reply(503, {"error": "The gateway did not confirm registration. The model may remain in the gateway without Keeplane approval; check Models."})
                return self.reply(status, result)
            if classes is None:
                return self.reply(200, {"name": name})
            params = resource["params"]
            model_revision = confirm_new_model(name, params)
            if model_revision is None:
                removed = undo_new_model(name, params)
                return self.reply(503, {"error": "The model did not answer through the gateway. " +
                                  ("Registration was removed." if removed else
                                   "It may remain in the gateway without Keeplane approval; check Models.")})
            try:
                approval = CATALOG.approve(name, classes, model_revision, self.actor(),
                                           owned_by_keeplane=True)
            except (ValueError, IdentityError, sqlite3.Error):
                removed = undo_new_model(name, params)
                return self.reply(503, {"error": "Keeplane could not save the model approval. " +
                                  ("Registration was removed." if removed else
                                   "It may remain in the gateway without Keeplane approval; check Models.")})
            return self.reply(200, {"name": name, "approved_classes": approval["approved_classes"]})
        if self.path == "/api/ask":
            model = body.get("model")
            prompt = body.get("prompt")
            if not isinstance(model, str) or not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
                return self.reply(400, {"error": "Choose a model and enter a prompt (up to 8000 characters)"})
            if CATALOG:
                approval = CATALOG.get(model)
                if approval is None:
                    return self.reply(403, {"error": "This model has not been set up for Keeplane"})
                resource_status, resource_result = gateway_model_resources()
                if resource_status != 200:
                    return self.reply(resource_status, resource_result)
                if approval["gateway_fingerprint"] != model_fingerprint(model, resource_result.get("resources", [])):
                    return self.reply(403, {"error": "This model changed in the gateway and must be set up again"})
            # This preview-only request has a fixed bound so a local runner
            # cannot spend the entire gateway timeout generating a smoke answer.
            request_body = {"model": model, "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 64}
            status, result = gateway("/v1/chat/completions", request_body,
                                     connection_retries=3)
            # A second gateway replica can briefly report model_not_found while
            # it applies a registration. That response has not reached a model.
            if status == 404 and isinstance(result.get("error"), dict) \
                    and result["error"].get("code") == "model_not_found":
                for delay in (0.1, 0.2, 0.4):
                    time.sleep(delay)
                    status, result = gateway("/v1/chat/completions", request_body,
                                             connection_retries=3)
                    if status != 404 or not isinstance(result.get("error"), dict) \
                            or result["error"].get("code") != "model_not_found":
                        break
            if status != 200:
                return self.reply(status, result)
            choice = result.get("choices", [{}])[0]
            return self.reply(200, {"model": model, "answer": choice.get("message", {}).get("content", "")})
        self.reply(404, {"error": "Not found"})

    def do_PUT(self):
        if IDENTITY and not self.require_admin(urlsplit(self.path).path):
            return
        if IDENTITY:
            segments = urlsplit(self.path).path.strip("/").split("/")
            if len(segments) == 4 and segments[:2] == ["api", "users"] and segments[3] == "role":
                if not self.identity_action_allowed():
                    return
                body = self.incoming()
                if body is None:
                    return
                return self.identity_result(lambda: (200, IDENTITY.change_role(segments[2], body.get("role"))))
        if IDENTITY and urlsplit(self.path).path == "/api/edition-note":
            if not self.identity_action_allowed():
                return
            body = self.incoming()
            if body is None:
                return
            return self.identity_result(lambda: (200, IDENTITY.set_edition_note(
                self.actor()[0], body.get("enabled"))))
        if IDENTITY:
            segments = urlsplit(self.path).path.strip("/").split("/")
            if DATA_CLASSES and segments == ["api", "data-classes", "mode"]:
                if not self.identity_action_allowed():
                    return
                body = self.incoming()
                if body is None:
                    return
                return self.identity_result(lambda: (200, DATA_CLASSES.set_enabled(
                    body.get("enabled"), self.actor())))
            if AUDIT and len(segments) == 4 and segments[:3] == ["api", "audit", "options"]:
                if not self.identity_action_allowed():
                    return
                body = self.incoming()
                if body is None:
                    return
                return self.identity_result(lambda: (200, {"options": AUDIT.set_option(
                    segments[3], body.get("enabled"))}))
            if DATA_CLASSES and len(segments) == 3 and segments[:2] == ["api", "data-classes"]:
                if not self.identity_action_allowed():
                    return
                body = self.incoming()
                if body is None:
                    return
                effective = set()
                if body.get("approved_model_ids"):
                    status, result, effective = effective_approval_ids()
                    if status != 200:
                        return self.reply(status, result)
                return self.identity_result(lambda: (200, DATA_CLASSES.edit(
                    segments[2], body, effective, self.actor())))
        self.reply(404, {"error": "Not found"})

    def do_DELETE(self):
        if IDENTITY and not self.require_admin(urlsplit(self.path).path):
            return
        segments = urlsplit(self.path).path.strip("/").split("/")
        if IDENTITY and len(segments) == 3 and segments[:2] == ["api", "users"]:
            if not self.identity_action_allowed():
                return
            return self.identity_result(lambda: (200, IDENTITY.delete_user(segments[2])))
        if DATA_CLASSES and len(segments) == 3 and segments[:2] == ["api", "data-classes"]:
            if not self.identity_action_allowed():
                return
            return self.identity_result(lambda: (200, DATA_CLASSES.remove(segments[2], self.actor())))
        if CATALOG and len(segments) == 4 and segments[:2] == ["api", "models"] and segments[3] == "setup":
            if not self.identity_action_allowed():
                return
            model_id = unquote(segments[2])
            try:
                approval = CATALOG.get(model_id)
                if approval is None:
                    return self.reply(404, {"error": "Model setup not found"})
                if approval["owned_by_keeplane"]:
                    status, resources = gateway_model_resources()
                    if status != 200:
                        return self.reply(status, resources)
                    resource = next((item.get("value", {}) for item in resources.get("resources", [])
                                     if item.get("id") == model_id), {})
                    if model_fingerprint(model_id, resources.get("resources", [])) != \
                            approval["gateway_fingerprint"]:
                        return self.reply(409, {"error": "The model changed in the gateway. "
                                                      "Keeplane will not remove a changed definition."})
                    status, result = gateway("/api/config/resources/llm.model/" + model_id,
                                             method="DELETE", timeout=10)
                    if status != 200:
                        return self.reply(status, result)
                    removed = CATALOG.remove(model_id, self.actor(), gateway_removed=True)
                    if approval["key_choice"] == "shared" and not remove_provider_key(
                            PROVIDER_KEY_DIR, provider_key_file(resource)):
                        return self.reply(503, {"error": "Model removed, but its shared key file needs cleanup"})
                    return self.reply(200, {"removed_from_keeplane": removed,
                                            "gateway_model_preserved": False})
                return self.reply(200, {"removed_from_keeplane": CATALOG.remove(model_id, self.actor()),
                                        "gateway_model_preserved": True})
            except IdentityError as error:
                return self.reply(error.status, {"error": error.message})
            except sqlite3.Error:
                return self.reply(503, {"error": "Keeplane settings storage is unavailable"})
        self.reply(404, {"error": "Not found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 3000), Handler).serve_forever()
