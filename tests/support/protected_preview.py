"""Authenticate transport checks against the protected local previews."""

import http.cookiejar
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import (
    BaseHandler,
    HTTPCookieProcessor,
    Request,
    build_opener,
    install_opener,
)


PASSWORD = Path("/private/tmp/keeplane-accounts-trial/first-admin-password")


def curl_csrf_headers(run, base, url, cookie):
    response = run(
        *base, "-c", str(cookie), "-b", str(cookie), url + "/api/auth-options"
    )
    token = json.loads(response.stdout)["csrf_token"]
    return ("-H", "X-CSRFToken: " + token)


class BrowserCsrfHandler(BaseHandler):
    handler_order = 400

    def __init__(self, base):
        self.base = base

    def http_request(self, request):
        if (
            urlsplit(request.full_url).netloc == urlsplit(self.base).netloc
            and urlsplit(request.full_url).scheme == urlsplit(self.base).scheme
            and request.get_method() not in {"GET", "HEAD", "OPTIONS"}
        ):
            with self.parent.open(
                self.base + "/api/auth-options", timeout=15
            ) as response:
                token = json.load(response)["csrf_token"]
            request.add_header("X-CSRFToken", token)
            request.add_header("Origin", self.base)
        return request

    https_request = http_request


def login_if_protected(base):
    if base not in {"http://127.0.0.1:3000", "http://127.0.0.1:13000"}:
        return False
    opener = build_opener(
        BrowserCsrfHandler(base), HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    opener.addheaders = [("X-Keeplane-Action", "1")]
    request = Request(
        base + "/api/session",
        method="POST",
        data=json.dumps(
            {"username": "first-admin", "password": PASSWORD.read_text().strip()}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    with opener.open(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError("Admin sign-in failed")
    install_opener(opener)
    return True
