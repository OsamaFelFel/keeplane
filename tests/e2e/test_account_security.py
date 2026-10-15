"""Sign-in limits and malformed account requests at the public HTTP edge."""

import json
import os
from pathlib import Path
import secrets
from urllib.error import HTTPError
from urllib.request import Request

from tests.support.client import BASE, Browser, RUNTIME


def sign_in(username, password):
    browser = Browser()
    status, options, _ = browser.fetch("/api/auth-options")
    if status != 200:
        raise RuntimeError("CSRF bootstrap failed")
    request = Request(
        BASE + "/api/session",
        method="POST",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={
            "Content-Type": "application/json",
            "Origin": BASE,
            "X-CSRFToken": options["csrf_token"],
        },
    )
    try:
        response = browser.opener.open(request, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, json.load(response)


def run_cases():
    cases = []
    admin = Browser()
    user_id = None
    password = secrets.token_urlsafe(20)
    username = "limit" + secrets.token_hex(6)
    try:
        code, _, _, _, _ = admin.login(
            "first-admin", (RUNTIME / "first-admin-password").read_text().strip()
        )
        if code != 200:
            raise RuntimeError("Could not sign in for account-security checks")
        status, user, _ = admin.fetch(
            "/api/users",
            {"username": username, "password": password, "role": "developer"},
            method="POST",
        )
        if status != 201:
            raise RuntimeError("Could not create the disposable account")
        user_id = user["id"]
        errors = []
        for case, account in (
            ("ACCT-24", username),
            ("ACCT-25", username + "-missing"),
        ):
            failures = [sign_in(account, "wrong-password")[0] for _ in range(5)]
            # Case changes must not provide a second budget.
            limited, headers, body = sign_in(account.upper(), password)
            retry = int(headers.get("Retry-After", "0"))
            errors.append(body.get("error"))
            passed = (
                failures == [401] * 5
                and limited == 429
                and 1 <= retry <= 60
                and not headers.get("Set-Cookie")
            )
            cases.append(
                {
                    "id": case,
                    "verdict": "pass" if passed else "fail",
                    "observed": {
                        "failed_statuses": failures,
                        "next_status": limited,
                        "retry_after": retry,
                        "session_issued": bool(headers.get("Set-Cookie")),
                    },
                }
            )
        if errors[0] != errors[1]:
            cases[-1]["verdict"] = "fail"

        anonymous = Browser()
        malformed, _, _ = anonymous.fetch("/api/session", [], method="POST")
        identity, _, _ = anonymous.fetch("/api/identity")
        cases.append(
            {
                "id": "ACCT-26",
                "verdict": "pass" if malformed == 400 and identity == 401 else "fail",
                "observed": {
                    "malformed_status": malformed,
                    "identity_status": identity,
                },
            }
        )
        statuses = []
        for path, method in (
            ("/api/users", "POST"),
            (f"/api/users/{user_id}/role", "PUT"),
            ("/api/edition-note", "PUT"),
        ):
            statuses.append(admin.fetch(path, [], method=method)[0])
        cases.append(
            {
                "id": "ACCT-27",
                "verdict": "pass" if statuses == [400] * 3 else "fail",
                "observed": {"malformed_mutation_statuses": statuses},
            }
        )
    finally:
        if user_id:
            removed, _, _ = admin.fetch(f"/api/users/{user_id}", {}, method="DELETE")
            if removed != 200:
                raise RuntimeError("Disposable account cleanup failed")
    report = {"base_url": BASE, "cases": cases}
    report_dir = Path(
        os.environ.get(
            "KEEPLANE_TEST_REPORT_DIR", "/private/tmp/keeplane-account-security"
        )
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "account-security.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report))
    if any(case["verdict"] != "pass" for case in cases):
        raise SystemExit(1)


if __name__ == "__main__":
    run_cases()


def test_account_security(monkeypatch, report_file, request, capsys):
    arguments = [__file__]
    monkeypatch.setattr("sys.argv", arguments)
    assert run_cases() in (None, 0)
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    verify_cases(__file__, output.out, globals().get("REPORT", report_file))
