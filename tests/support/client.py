"""Spec 003 local account and Open Source edition-boundary checks."""

import http.cookiejar
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


BASE = os.environ.get("KEEPLANE_BASE_URL", "http://127.0.0.1:3000").rstrip("/")
LEGACY_RUNTIME = Path("/private/tmp/keeplane-accounts-trial")
RUNTIME = Path(
    os.environ.get(
        "KEEPLANE_RUNTIME_DIR",
        LEGACY_RUNTIME
        if LEGACY_RUNTIME.is_dir()
        else Path(__file__).resolve().parents[2] / ".keeplane/local",
    )
)


class Browser:
    def __init__(self, base=BASE):
        self.base = base.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def fetch(
        self, path, payload=None, action=True, method=None, csrf=True, headers=None
    ):
        supplied_headers = headers or {}
        headers = {"Accept": "application/json"}
        actual_method = method or ("POST" if payload is not None else "GET")
        if csrf and actual_method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            status, options, _ = self.fetch("/api/auth-options")
            if status != 200 or not options.get("csrf_token"):
                raise RuntimeError("CSRF bootstrap failed")
            headers["X-CSRFToken"] = options["csrf_token"]
            headers["Origin"] = self.base
        headers.update(supplied_headers)
        if payload is not None:
            headers["Content-Type"] = "application/json"
            if action:
                headers["X-Keeplane-Action"] = "1"
        request = Request(
            self.base + path,
            None if payload is None else json.dumps(payload).encode(),
            headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read().decode()
                return response.status, json.loads(raw) if raw else None, response.url
        except HTTPError as error:
            raw = error.read().decode()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"error": raw[:120]}
            return error.code, data, error.url

    def page(self, path):
        try:
            with self.opener.open(self.base + path, timeout=20) as response:
                return response.status, response.url, response.read().decode()
        except HTTPError as error:
            return error.code, error.url, error.read().decode()

    def login(self, username, password):
        sign_status, sign_url, sign_page = self.page("/")
        if sign_status != 200 or sign_url != self.base + "/sign-in":
            raise RuntimeError("Keeplane sign-in page was not returned")
        code, result, url = self.fetch(
            "/api/session", {"username": username, "password": password}, method="POST"
        )
        if code != 200:
            return code, url, json.dumps(result), sign_url, sign_page
        status, url, page = self.page("/")
        return status, url, page, sign_url, sign_page
