"""Local preview edge: static UI, health, and protected Django API proxy."""

import json
import http.client
import os
import time
from http.cookies import SimpleCookie
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import ThreadingMixIn
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from local_identity import LocalIdentity
from audit import AuditStore
from storage_errors import StorageUnavailable
from runner_adapter import local_runner as inspect_local_runner


GATEWAY = os.environ.get("GATEWAY_URL", "http://gateway:4000")
GATEWAY_RUNTIME_KEY_FILE = os.environ.get("GATEWAY_RUNTIME_KEY_FILE", "")
GATEWAY_ADMIN_KEY_FILE = os.environ.get("GATEWAY_ADMIN_KEY_FILE", "")
UI = Path("/ui")
MAX_BODY = 64 * 1024
RUNNER_URLS = {url.strip().rstrip("/") for url in
               os.environ.get("PREVIEW_RUNNER_URLS", "http://qwen:8080").split(",") if url.strip()}


if os.environ.get("KEEPLANE_DATABASE_HOST"):
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_api.settings")
    django.setup()
    from django_api.persistence import stores
    AUDIT, IDENTITY, _, _ = stores()
else:
    AUDIT = AuditStore(os.environ["MODEL_APPROVAL_DB"]) \
    if os.environ.get("ACCOUNT_DB") and os.environ.get("MODEL_APPROVAL_DB") else None
    IDENTITY = LocalIdentity(os.environ["ACCOUNT_DB"], os.environ["FIRST_ADMIN_PASSWORD_FILE"], AUDIT) \
    if os.environ.get("ACCOUNT_DB") else None
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "")
DJANGO_ACCOUNT_PORT = 8765


def account_api_path(path):
    return path in {"/api/auth-options", "/api/session", "/api/identity", "/api/users",
                    "/api/edition-note", "/api/edition-note/consume", "/sign-out"} or \
        path.startswith(("/api/users/", "/api/user-operations/"))


def django_model_path(path):
    return path in {"/api/models", "/api/runners/models", "/api/ask"} or \
        (path.startswith("/api/models/") and path.endswith("/setup"))


def settings_api_path(path):
    return path == "/api/data-classes" or path.startswith("/api/data-classes/") or \
        path in {"/api/audit/options", "/api/audit/records"} or \
        path.startswith("/api/audit/options/")


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


class Handler(BaseHTTPRequestHandler):
    def forward_account_api(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_BODY:
                return self.reply(413, {"error": "Request is too large"})
            body = self.rfile.read(length) if length else None
            headers = {name: self.headers[name] for name in
                       ("Cookie", "Content-Type", "Origin", "Referer", "X-CSRFToken",
                        "X-Keeplane-Action", "Accept")
                       if name in self.headers}
            headers["X-Keeplane-Scheme"] = urlsplit(PUBLIC_ORIGIN).scheme or "http"
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

    def session_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return cookie["keeplane_session"].value if "keeplane_session" in cookie else ""
        except Exception:
            return ""

    def signed_in_user(self):
        if not os.environ.get("KEEPLANE_DATABASE_HOST"):
            return IDENTITY.session(self.session_token())
        # Static-edge threads are outside Django's request lifecycle.
        from django.db import close_old_connections, connections
        close_old_connections()
        try:
            return IDENTITY.session(self.session_token())
        finally:
            connections.close_all()

    def require_admin(self, path):
        if not IDENTITY:
            return True
        try:
            self._signed_in_user = self.signed_in_user()
        except StorageUnavailable:
            self.reply(503, {"error": "Keeplane storage is unavailable; contact your operator"})
            return False
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

    def do_GET(self):
        route = urlsplit(self.path)
        path = route.path
        if path == "/api/models" or settings_api_path(path) or account_api_path(path):
            return self.forward_account_api()
        if IDENTITY:
            if path == "/sign-in":
                return self.reply(200, (UI / "sign-in.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/":
                try:
                    developer = (self.signed_in_user() or {}).get("role") == "developer"
                except StorageUnavailable:
                    return self.reply(503, {"error": "Keeplane storage is unavailable; contact your operator"})
                if developer:
                    self.send_response(302)
                    self.send_header("Location", "/app/")
                    self.end_headers()
                    return
            if path not in ("/health/app", "/style.css", "/sign-in.js", "/browser-security.js", "/app", "/app/", "/app/data-classes", "/app/audit", "/app/models") \
                    and not path.startswith(("/fonts/", "/app/assets/")) \
                    and not self.require_admin(path):
                return
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
        elif self.path in ("/", "/style.css", "/app.js", "/sign-in.js", "/browser-security.js"):
            name = "index.html" if self.path == "/" else self.path[1:]
            content_type = {"index.html": "text/html", "style.css": "text/css",
                            "app.js": "text/javascript", "sign-in.js": "text/javascript",
                            "browser-security.js": "text/javascript"}[name]
            self.reply(200, (UI / name).read_bytes(), content_type + "; charset=utf-8")
        elif self.path in ("/fonts/IBMPlexSans-Regular.woff2", "/fonts/IBMPlexSans-SemiBold.woff2",
                           "/fonts/IBMPlexMono-Regular.woff2"):
            self.reply(200, (UI / self.path[1:]).read_bytes(), "font/woff2")
        else:
            self.reply(404, {"error": "Not found"})

    def browser_change(self):
        path = urlsplit(self.path).path
        if django_model_path(path) or settings_api_path(path) or account_api_path(path):
            return self.forward_account_api()
        self.reply(404, {"error": "Not found"})

    do_POST = browser_change
    do_PUT = browser_change
    do_DELETE = browser_change


if __name__ == "__main__":
    # A chart packaging probe without account storage serves assets and health
    # only; every API still proxies and fails closed. Protected installations
    # always start Django, with no legacy-account fallback or opt-out flag.
    if IDENTITY:
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
