"""Spec 003 local account and Open Source edition-boundary checks."""

import http.cookiejar
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
from reporting import report_path


BASE = "http://127.0.0.1:3000"
RUNTIME = Path("/private/tmp/keeplane-accounts-trial")
REPORT = report_path("2026-10-09-edition-boundary-accounts.json")


class Browser:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def fetch(self, path, payload=None, action=True, method=None):
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
            if action:
                headers["X-Keeplane-Action"] = "1"
        request = Request(BASE + path,
                          None if payload is None else json.dumps(payload).encode(),
                          headers, method=method)
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
            with self.opener.open(BASE + path, timeout=20) as response:
                return response.status, response.url, response.read().decode()
        except HTTPError as error:
            return error.code, error.url, error.read().decode()

    def login(self, username, password):
        sign_status, sign_url, sign_page = self.page("/")
        if sign_status != 200 or sign_url != BASE + "/sign-in":
            raise RuntimeError("Keeplane sign-in page was not returned")
        code, result, url = self.fetch("/api/session", {"username": username,
                                                          "password": password}, method="POST")
        if code != 200:
            return code, url, json.dumps(result), sign_url, sign_page
        status, url, page = self.page("/")
        return status, url, page, sign_url, sign_page


def main():
    cases = []
    users = []
    prefix = "acct" + secrets.token_hex(3)
    admin = None

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    try:
        anonymous = Browser()
        status, _, _ = anonymous.fetch("/api/users")
        admin = Browser()
        code, url, _, sign_url, sign_page = admin.login(
            "first-admin", (RUNTIME / "first-admin-password").read_text().strip())
        record("ACCT-01", status == 401 and sign_url == BASE + "/sign-in",
               {"api_status": status, "sign_in_page": sign_url})
        record("ACCT-11", "Create an account" not in sign_page and
               'id="sign-in-form"' in sign_page,
               {"self_registration_control": "Create an account" in sign_page})
        status, _, _ = admin.fetch("/api/models")
        users_status, _, users_page = admin.page("/users")
        record("ACCT-02", code == 200 and url == BASE + "/" and status == 200 and
               users_status == 200 and "Create user" in users_page,
               {"login_status": code, "users_page_status": users_status,
                "model_api_status": status})

        try:
            with urlopen(Request(BASE + "/api/users", headers={"X-Forwarded-User":
                         "00000000-0000-0000-0000-000000000001"}), timeout=10) as response:
                spoof_status = response.status
        except HTTPError as error:
            spoof_status = error.code
        record("ACCT-14", spoof_status == 401,
               {"forwarded_identity_without_session_status": spoof_status})
        wrong = Browser()
        wrong_status, _, _, _, _ = wrong.login("first-admin", "wrong-password")
        wrong_api_status, _, _ = wrong.fetch("/api/users")
        record("ACCT-15", wrong_status == 401 and wrong_api_status == 401,
               {"wrong_password_status": wrong_status, "api_status": wrong_api_status})

        signed_out = Browser()
        signed_out.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
        signed_out.page("/sign-out")
        status, _, _ = signed_out.fetch("/api/users")
        sign_status, _, signed_out_page = signed_out.page("/")
        record("ACCT-03", status == 401 and sign_status == 200 and
               'id="sign-in-form"' in signed_out_page,
               {"api_after_signout": status, "sign_in_form_after_signout":
                'id="sign-in-form"' in signed_out_page})

        created = {}
        passwords = {}
        for role in ("developer", "admin"):
            username = prefix + "-" + role
            passwords[role] = secrets.token_urlsafe(20)
            status, value, _ = admin.fetch("/api/users", {"username": username,
                "password": passwords[role], "role": role}, method="POST")
            if status != 201:
                raise RuntimeError(f"Could not create trial {role}: HTTP {status}: {value}")
            users.append(value["id"])
            created[role] = value
        status, listing, _ = admin.fetch("/api/users?search=" + prefix)
        role_map = {user["username"]: user["role"] for user in listing.get("users", [])}
        record("ACCT-04", status == 200 and all(
            role_map.get(created[role]["username"]) == role for role in created),
            {"list_status": status, "roles": role_map})

        developer = Browser()
        code, url, _, _, _ = developer.login(created["developer"]["username"], passwords["developer"])
        record("ACCT-05", code == 403 and url == BASE + "/api/session",
               {"login_status": code, "denied_at_session": url == BASE + "/api/session"})
        another_admin = Browser()
        code, url, _, _, _ = another_admin.login(created["admin"]["username"], passwords["admin"])
        record("ACCT-06", code == 200 and url == BASE + "/",
               {"login_status": code, "page": url})

        for number in range(25):
            status, user, _ = admin.fetch("/api/users", {
                "username": f"{prefix}-page-{number:02}",
                "password": secrets.token_urlsafe(20), "role": "developer"}, method="POST")
            if status != 201:
                raise RuntimeError(f"Could not create paging user {number}: HTTP {status}: {user}")
            users.append(user["id"])
        names = set()
        pages = []
        for page in (1, 2):
            status, result, _ = admin.fetch(f"/api/users?search={prefix}&page={page}&page_size=20")
            pages.append({"status": status, "count": len(result.get("users", [])),
                          "has_more": result.get("has_more")})
            names.update(item["username"] for item in result.get("users", []))
        status, focused, _ = admin.fetch(f"/api/users?search={prefix}-admin&page=1&page_size=20")
        record("ACCT-07", pages[0]["count"] == 20 and pages[0]["has_more"] and
               pages[1]["count"] == 7 and not pages[1]["has_more"] and
               len(names) == 27 and status == 200 and len(focused.get("users", [])) == 1,
               {"pages": pages, "unique_names": len(names), "focused_count": len(focused.get("users", []))})

        denied_status, _, _ = admin.fetch("/api/users", {"username": prefix + "-denied",
            "password": secrets.token_urlsafe(20), "role": "developer"},
            action=False, method="POST")
        record("ACCT-10", denied_status == 403, {"mutation_status": denied_status})
        admin_status, _, _ = admin.fetch("/api/status")
        try:
            with urlopen(BASE + "/api/status", timeout=10) as response:
                anonymous_status = response.status
        except HTTPError as error:
            anonymous_status = error.code
        record("ACCT-12", admin_status == 200 and anonymous_status == 401,
               {"admin_model_status": admin_status, "anonymous_model_status": anonymous_status})

        blocked = {}
        for path, payload, method in (("/api/teams", None, None),
                                      ("/api/teams?q=old", None, None),
                                      ("/api/teams/old", None, None),
                                      ("/api/teams/old/members", None, None),
                                      ("/api/teams", {"name": "old"}, "POST"),
                                      ("/api/teams/old/members/person", {}, "PUT"),
                                      ("/api/teams/old", {}, "DELETE")):
            blocked[f"{method or 'GET'} {path}"] = admin.fetch(path, payload, method=method)[0]
        team_page = admin.page("/teams")[0]
        team_detail = admin.page("/teams/old")[0]
        record("ACCT-08", all(value == 404 for value in blocked.values()) and
               team_page == 404 and team_detail == 404,
               {"api_statuses": blocked, "team_page": team_page, "team_detail": team_detail})

        page_statuses = {}
        leaked_nav = []
        for path in ("/", "/users", "/data-classes", "/audit", "/editions"):
            page_status, _, page = admin.page(path)
            page_statuses[path] = page_status
            if 'href="/teams"' in page:
                leaked_nav.append(path)
        editions_status, _, editions_page = admin.page("/editions")
        record("ACCT-09", all(status == 200 for status in page_statuses.values()) and
               not leaked_nav and editions_status == 200 and
               "Open Source includes" in editions_page and "Enterprise adds" in editions_page and
               'id="ent-notes"' in editions_page and "How to get Enterprise" in editions_page and
               'href="/teams"' not in editions_page,
               {"page_statuses": page_statuses, "team_navigation": leaked_nav,
                "editions_status": editions_status})

        # Reset the note first so repeated test runs have the same first-view state.
        admin.fetch("/api/edition-note", {"enabled": False}, method="PUT")
        off_status, off_state, _ = admin.fetch("/api/edition-note")
        off_consume = admin.fetch("/api/edition-note/consume", {}, method="POST")
        admin.fetch("/api/edition-note", {"enabled": True}, method="PUT")
        on_status, on_state, _ = admin.fetch("/api/edition-note")
        first_consume = admin.fetch("/api/edition-note/consume", {}, method="POST")
        second_consume = admin.fetch("/api/edition-note/consume", {}, method="POST")
        record("ACCT-13", off_status == 200 and off_state == {"enabled": False} and
               off_consume[1] == {"show": False} and on_status == 200 and
               on_state == {"enabled": True} and first_consume[1] == {"show": True} and
               second_consume[1] == {"show": False},
               {"off": off_state, "first_view": first_consume[1],
                "repeat_view": second_consume[1]})
    finally:
        failed_cleanup = 0
        if admin:
            # Leave the local preview ready for the owner to see the one-time note.
            for enabled in (False, True):
                try:
                    status, _, _ = admin.fetch("/api/edition-note", {"enabled": enabled}, method="PUT")
                    failed_cleanup += status != 200
                except Exception:
                    failed_cleanup += 1
            for user_id in users:
                try:
                    status, _, _ = admin.fetch("/api/users/" + user_id, {}, method="DELETE")
                    failed_cleanup += status != 200
                except Exception:
                    failed_cleanup += 1
        report = {"suite": "Spec 003 Open Source account and edition trial",
                  "time_utc": datetime.now(timezone.utc).isoformat(),
                  "identity": "Keeplane local SQLite trial",
                  "cases": cases, "cleanup": "complete" if not failed_cleanup else
                             f"{failed_cleanup} actions failed",
                  "passed": sum(c["verdict"] == "pass" for c in cases),
                  "failed": sum(c["verdict"] == "fail" for c in cases)}
        REPORT.write_text(json.dumps(report, indent=2) + "\n")
        print(f"{report['passed']} passed, {report['failed']} failed; cleanup {report['cleanup']}; {REPORT}")
        for case in cases:
            print(case["id"], case["verdict"], case["observed"])
        if report["failed"] or failed_cleanup:
            sys.exit(1)


if __name__ == "__main__":
    main()
