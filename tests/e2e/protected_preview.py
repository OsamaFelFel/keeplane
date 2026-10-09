"""Authenticate legacy transport checks when aimed at the protected Docker UI."""

import http.cookiejar
import json
from pathlib import Path
from urllib.request import HTTPCookieProcessor, Request, build_opener, install_opener


PASSWORD = Path("/private/tmp/keeplane-accounts-trial/first-admin-password")


def login_if_protected(base):
    if base != "http://127.0.0.1:3000":
        return False
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.addheaders = [("X-Keeplane-Action", "1")]
    request = Request(base + "/api/session", method="POST",
                      data=json.dumps({"username": "first-admin",
                                       "password": PASSWORD.read_text().strip()}).encode(),
                      headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError("Admin sign-in failed")
    install_opener(opener)
    return True
