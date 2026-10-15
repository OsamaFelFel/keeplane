"""CSRF rejection and session preservation through the public browser edge."""

import json
import os
from pathlib import Path

from tests.support.client import BASE, Browser, RUNTIME


def run_cases():
    cases = []
    browser = Browser()
    password = (RUNTIME / "first-admin-password").read_text().strip()
    credentials = {"username": "first-admin", "password": password}

    def record(identifier, passed, observed):
        cases.append(
            {
                "id": identifier,
                "verdict": "pass" if passed else "fail",
                "observed": observed,
            }
        )

    with browser.opener.open(BASE + "/api/auth-options", timeout=15) as response:
        old_token = json.load(response)["csrf_token"]
        cookie_header = response.headers.get("Set-Cookie", "")
        record(
            "CSRF-01",
            len(old_token) == 64
            and "HttpOnly" in cookie_header
            and "SameSite=Strict" in cookie_header
            and response.headers.get("Cache-Control") == "no-store",
            {
                "masked_token": len(old_token) == 64,
                "httponly_cookie": "HttpOnly" in cookie_header,
                "strict_cookie": "SameSite=Strict" in cookie_header,
                "cache_control": response.headers.get("Cache-Control"),
            },
        )
    old_cookie = next(
        cookie.value for cookie in browser.cookies if cookie.name == "csrftoken"
    )
    rejected = []
    rejected.append(
        browser.fetch("/api/session", credentials, method="POST", csrf=False)[0]
    )
    rejected.append(
        browser.fetch(
            "/api/session",
            credentials,
            method="POST",
            csrf=False,
            headers={"X-CSRFToken": "a" * 64, "Origin": BASE},
        )[0]
    )
    rejected.append(
        browser.fetch(
            "/api/session",
            credentials,
            method="POST",
            csrf=False,
            headers={"X-CSRFToken": old_token, "Origin": "https://foreign.example"},
        )[0]
    )
    identity_before = browser.fetch("/api/identity")[0]
    record(
        "CSRF-02",
        rejected == [403] * 3 and identity_before == 401,
        {"rejected_login_statuses": rejected, "identity_status": identity_before},
    )

    other = Browser()
    other_token = other.fetch("/api/auth-options")[1]["csrf_token"]
    mixed = browser.fetch(
        "/api/session",
        credentials,
        method="POST",
        csrf=False,
        headers={"X-CSRFToken": other_token, "Origin": BASE},
    )[0]
    record("CSRF-03", mixed == 403, {"different_browser_token_status": mixed})
    signed = browser.fetch("/api/session", credentials, method="POST")[0]
    new_cookie = next(
        cookie.value for cookie in browser.cookies if cookie.name == "csrftoken"
    )
    original = browser.fetch("/api/edition-note")[1]["enabled"]
    stale = browser.fetch(
        "/api/edition-note",
        {"enabled": not original},
        method="PUT",
        csrf=False,
        headers={"X-CSRFToken": old_token, "Origin": BASE},
    )[0]
    unchanged = browser.fetch("/api/edition-note")[1]["enabled"] == original
    record(
        "CSRF-04",
        signed == 200 and old_cookie != new_cookie and stale == 403 and unchanged,
        {
            "login_status": signed,
            "token_rotated": old_cookie != new_cookie,
            "pre_login_token_status": stale,
            "setting_unchanged": unchanged,
        },
    )

    routes = [
        ("/api/session", "POST"),
        ("/api/users", "POST"),
        ("/api/users/unknown", "DELETE"),
        ("/api/users/unknown/role", "PUT"),
        ("/api/models", "POST"),
        ("/api/models/unknown/setup", "POST"),
        ("/api/models/unknown/setup", "DELETE"),
        ("/api/runners/models", "POST"),
        ("/api/ask", "POST"),
        ("/api/data-classes", "POST"),
        ("/api/data-classes/mode", "PUT"),
        ("/api/data-classes/unknown", "PUT"),
        ("/api/data-classes/unknown", "DELETE"),
        ("/api/audit/options/settings", "PUT"),
        ("/api/edition-note", "PUT"),
        ("/api/edition-note/consume", "POST"),
        ("/sign-out", "POST"),
    ]
    statuses = [
        browser.fetch(path, {}, method=method, csrf=False)[0] for path, method in routes
    ]
    record(
        "CSRF-05",
        statuses == [403] * len(routes),
        {"unsafe_routes_checked": len(routes), "statuses": statuses},
    )
    get_status = browser.page("/sign-out")[0]
    still_signed = browser.fetch("/api/identity")[0]
    record(
        "CSRF-06",
        get_status == 405 and still_signed == 200,
        {
            "get_sign_out_status": get_status,
            "identity_after_rejected_sign_out": still_signed,
        },
    )

    changed = browser.fetch(
        "/api/edition-note", {"enabled": not original}, method="PUT"
    )[0]
    visible = browser.fetch("/api/edition-note")[1]["enabled"] == (not original)
    restored = browser.fetch("/api/edition-note", {"enabled": original}, method="PUT")[
        0
    ]
    record(
        "CSRF-07",
        changed == 200 and visible and restored == 200,
        {
            "valid_change_status": changed,
            "change_visible": visible,
            "restore_status": restored,
        },
    )
    out = browser.fetch("/sign-out", method="POST")[0]
    after = browser.fetch("/api/identity")[0]
    record(
        "CSRF-08",
        out == 200
        and after == 401
        and not any(cookie.name == "keeplane_session" for cookie in browser.cookies),
        {
            "post_sign_out_status": out,
            "identity_status": after,
            "session_cookie_removed": not any(
                cookie.name == "keeplane_session" for cookie in browser.cookies
            ),
        },
    )
    report = {"base_url": BASE, "cases": cases}
    directory = Path(
        os.environ.get("KEEPLANE_TEST_REPORT_DIR", "/private/tmp/keeplane-csrf")
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "csrf.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    if any(case["verdict"] != "pass" for case in cases):
        raise SystemExit(1)


if __name__ == "__main__":
    run_cases()


def test_csrf(monkeypatch, report_file, request):
    arguments = [__file__]
    monkeypatch.setattr("sys.argv", arguments)
    assert run_cases() in (None, 0)
