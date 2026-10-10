"""Protected Docker checks for always-on break-glass sign-in records."""

import json

from reporting import report_path
from test_accounts import BASE, Browser, RUNTIME


REPORT = report_path("2026-10-10-break-glass-audit.json")


def main():
    cases = []

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    password = (RUNTIME / "first-admin-password").read_text().strip()
    admin = Browser()
    status, _, _, _, _ = admin.login("first-admin", password)
    records_status, first, _ = admin.fetch("/api/audit/records?kind=break_glass_sign_ins")
    record("BG-07", status == 200 and records_status == 200 and first["total"] >= 1 and
           first["records"][0]["who"] == "first-admin" and
           first["records"][0]["what"] == "Break-glass admin signed in.",
           {"login_status": status, "records_status": records_status,
            "sign_in_records": first.get("total")})

    another = Browser()
    repeated_status, _, _, _, _ = another.login("first-admin", password)
    _, second, _ = admin.fetch("/api/audit/records?kind=break_glass_sign_ins")
    wrong = Browser()
    wrong_status, _, _, _, _ = wrong.login("first-admin", "wrong-password")
    _, after_wrong, _ = admin.fetch("/api/audit/records?kind=break_glass_sign_ins")
    record("BG-08", repeated_status == 200 and second["total"] == first["total"] + 1 and
           wrong_status == 401 and after_wrong["total"] == second["total"],
           {"repeated_status": repeated_status, "wrong_password_status": wrong_status,
            "records_added_by_repeat": second["total"] - first["total"],
            "records_added_by_bad_password": after_wrong["total"] - second["total"]})

    options_status, options, _ = admin.fetch("/api/audit/options")
    switch_status, _, _ = admin.fetch("/api/audit/options/break_glass_sign_ins",
                                      {"enabled": False}, method="PUT")
    page_status, page_url, page = admin.page("/audit")
    record("BG-09", options_status == 200 and "break_glass_sign_ins" not in options["options"] and
           switch_status == 400 and page_status == 200 and page_url == BASE + "/app/audit" and
           'id="root"' in page,
           {"options_status": options_status, "switch_status": switch_status,
            "page_status": page_status})

    REPORT.write_text(json.dumps({"cases": cases}, indent=2) + "\n")
    print(json.dumps({"results": cases}))
    if any(case["verdict"] != "pass" for case in cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
