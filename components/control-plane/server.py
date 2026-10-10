"""Local preview entry point: UI, legacy settings, and Django API proxy."""

import json
import http.client
import os
import sqlite3
import time
from http.cookies import SimpleCookie
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import ThreadingMixIn
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from local_identity import IdentityError, LocalIdentity
from audit import AuditError, AuditStore
from data_classes import DataClassError, DataClassStore
from model_catalog import ModelCatalog, fingerprint
from runner_adapter import local_runner as inspect_local_runner


GATEWAY = os.environ.get("GATEWAY_URL", "http://gateway:4000")
GATEWAY_RUNTIME_KEY_FILE = os.environ.get("GATEWAY_RUNTIME_KEY_FILE", "")
GATEWAY_ADMIN_KEY_FILE = os.environ.get("GATEWAY_ADMIN_KEY_FILE", "")
UI = Path("/ui")
MAX_BODY = 64 * 1024
RUNNER_URLS = {url.strip().rstrip("/") for url in
               os.environ.get("PREVIEW_RUNNER_URLS", "http://qwen:8080").split(",") if url.strip()}


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
DJANGO_ACCOUNT_API = os.environ.get("DJANGO_ACCOUNT_API") == "1"
DJANGO_ACCOUNT_PORT = 8765


def account_api_path(path):
    return path in {"/api/auth-options", "/api/session", "/api/identity", "/api/users",
                    "/api/edition-note", "/api/edition-note/consume", "/sign-out"} or \
        path.startswith(("/api/users/", "/api/user-operations/"))


def django_model_path(path):
    return path in {"/api/models", "/api/runners/models"} or \
        (path.startswith("/api/models/") and path.endswith("/setup"))


def model_fingerprint(model_id, resources):
    return fingerprint(model_id, resources, GATEWAY_FILE_CONFIG)


def local_runner(address, model=None):
    # Keep discovery callable for the standalone runner context trial.
    return inspect_local_runner(address, RUNNER_URLS, model)


def gateway(path, body=None, method=None, connection_retries=0, timeout=120):
    payload = None if body is None else json.dumps(body).encode()
    request = Request(GATEWAY + path, data=payload, method=method or ("POST" if payload is not None else "GET"))
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    key_file = GATEWAY_ADMIN_KEY_FILE if path.startswith("/api/") else GATEWAY_RUNTIME_KEY_FILE
    if key_file:
        try:
            key = Path(key_file).read_text().strip()
        except OSError:
            key = ""
        if not key:
            return 503, {"error": "Gateway credential unavailable"}
        request.add_header("Authorization", "Bearer " + key)
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


class Handler(BaseHTTPRequestHandler):
    def forward_account_api(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_BODY:
                return self.reply(413, {"error": "Request is too large"})
            body = self.rfile.read(length) if length else None
            headers = {name: self.headers[name] for name in
                       ("Cookie", "Content-Type", "Origin", "X-Keeplane-Action", "Accept")
                       if name in self.headers}
            route = urlsplit(self.path)
            target = route.path + ("?" + route.query if route.query else "")
            timeout = 300 if self.command == "POST" and django_model_path(route.path) else 15
            connection = http.client.HTTPConnection("127.0.0.1", DJANGO_ACCOUNT_PORT, timeout=timeout)
            try:
                connection.request(self.command, target, body=body, headers=headers)
                upstream = connection.getresponse()
                content = upstream.read()
                self.send_response(upstream.status)
                for name, value in upstream.getheaders():
                    if name.lower() not in {"server", "date", "connection", "transfer-encoding", "content-length"}:
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            finally:
                connection.close()
        except (OSError, http.client.HTTPException):
            self.reply(503, {"error": "Keeplane API is unavailable"})

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
        if path == "/api/models" or (DJANGO_ACCOUNT_API and account_api_path(path)):
            return self.forward_account_api()
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
            if path not in ("/health/app", "/style.css", "/sign-in.js", "/app", "/app/", "/app/data-classes", "/app/audit", "/app/models") \
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
        elif path in ("/app", "/app/", "/app/data-classes", "/app/audit", "/app/models"):
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
        if django_model_path(path) or (DJANGO_ACCOUNT_API and account_api_path(path)):
            return self.forward_account_api()
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
        if DJANGO_ACCOUNT_API and account_api_path(urlsplit(self.path).path):
            return self.forward_account_api()
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
        path = urlsplit(self.path).path
        segments = path.strip("/").split("/")
        model_setup_path = len(segments) == 4 and segments[:2] == ["api", "models"] and segments[3] == "setup"
        if model_setup_path or (DJANGO_ACCOUNT_API and account_api_path(path)):
            return self.forward_account_api()
        if IDENTITY and not self.require_admin(path):
            return
        if IDENTITY and len(segments) == 3 and segments[:2] == ["api", "users"]:
            if not self.identity_action_allowed():
                return
            return self.identity_result(lambda: (200, IDENTITY.delete_user(segments[2])))
        if DATA_CLASSES and len(segments) == 3 and segments[:2] == ["api", "data-classes"]:
            if not self.identity_action_allowed():
                return
            return self.identity_result(lambda: (200, DATA_CLASSES.remove(segments[2], self.actor())))
        self.reply(404, {"error": "Not found"})


if __name__ == "__main__":
    if DJANGO_ACCOUNT_API:
        from django.core.wsgi import get_wsgi_application
        from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_api.settings")

        class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
            daemon_threads = True

        account_server = make_server("127.0.0.1", DJANGO_ACCOUNT_PORT,
                                     get_wsgi_application(), server_class=ThreadingWSGIServer,
                                     handler_class=WSGIRequestHandler)
        Thread(target=account_server.serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 3000), Handler).serve_forever()
