"""Live complexity levels and the removal guard against a running preview.

Spec 004 ST13 and ST23 (D121), Spec 006 ST21. The plain-English cases are in
complexity-levels-cases.md. Needs the protected Docker or kind preview.
"""

import uuid

from tests.support.client import RUNTIME, Browser


def levels(browser):
    status, body, _ = browser.fetch("/api/models")
    assert status == 200, body
    return {row["level"]: row for row in body["levels"]}


def test_complexity_levels_live():
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    name = "keeplane-level-" + uuid.uuid4().hex[:10]
    status, options, _ = browser.fetch("/api/audit/options")
    assert status == 200, options
    settings_audit = options["options"]["settings"]
    original = {level: row["admin_model_id"] for level, row in levels(browser).items()}
    try:
        if not settings_audit:
            assert (
                browser.fetch(
                    "/api/audit/options/settings", {"enabled": True}, method="PUT"
                )[0]
                == 200
            )
        # LEVEL-LIVE-01: every level has a model once one is set up.
        status, body, _ = browser.fetch(
            "/api/models",
            {
                "name": name,
                "model": "mock-local",
                "source": "fixture",
                "approved_classes": [],
            },
        )
        assert status == 200, body
        rows = levels(browser)
        assert set(rows) == {"simple", "standard", "complex"}
        assert all(row["model_id"] for row in rows.values())

        # LEVEL-LIVE-02: an admin changes Complex; it is recorded.
        status, body, _ = browser.fetch(
            "/api/levels/complex", {"model_id": name}, method="POST"
        )
        assert status == 200, body
        complex_row = levels(browser)["complex"]
        assert complex_row["model_id"] == name and complex_row["changed_by_admin"]
        status, records, _ = browser.fetch(
            "/api/audit/records?kind=settings&search=complexity"
        )
        assert status == 200
        assert any(
            row["what"].startswith("Changed complexity pick Complex: ")
            and row["what"].endswith(f" to model {name}")
            and row["who"] == "first-admin"
            for row in records["records"]
        ), records

        # LEVEL-LIVE-03: the model can't be removed while Complex uses it.
        status, body, _ = browser.fetch(
            f"/api/models/{name}/setup", {}, method="DELETE"
        )
        assert status == 409 and body["in_use"]["levels"] == ["Complex"], body
        assert any(
            item["id"] == name for item in browser.fetch("/api/models")[1]["models"]
        )

        # LEVEL-LIVE-04: back to Keeplane's pick, then removal works.
        status, body, _ = browser.fetch(
            "/api/levels/complex", {"model_id": original["complex"]}, method="POST"
        )
        assert status == 200, body
        status, body, _ = browser.fetch(
            f"/api/models/{name}/setup", {}, method="DELETE"
        )
        assert status == 200, body
        name = None
    finally:
        if name:
            browser.fetch(
                "/api/levels/complex", {"model_id": original["complex"]}, method="POST"
            )
            browser.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
        if not settings_audit:
            browser.fetch(
                "/api/audit/options/settings", {"enabled": False}, method="PUT"
            )
