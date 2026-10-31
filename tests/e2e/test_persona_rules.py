"""Live persona rules and the removal guard against a running preview.

Spec 004 ST15 and ST23 (D121), Spec 006 ST21. The plain-English cases are in
persona-rules-cases.md. Needs the protected Docker or kind preview.
"""

import uuid

from tests.support.client import RUNTIME, Browser


def rules(browser):
    status, body, _ = browser.fetch("/api/models")
    assert status == 200, body
    return {row["persona"]: row for row in body["persona_rules"]}


def test_persona_rules_live():
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    name = "keeplane-rule-" + uuid.uuid4().hex[:10]
    status, options, _ = browser.fetch("/api/audit/options")
    assert status == 200, options
    settings_audit = options["options"]["settings"]
    original = rules(browser).get("architect", {}).get("model_id")
    try:
        if not settings_audit:
            assert (
                browser.fetch(
                    "/api/audit/options/settings", {"enabled": True}, method="PUT"
                )[0]
                == 200
            )
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

        # RULE-LIVE-01: an admin adds an Architect rule; it shows and is recorded.
        status, body, _ = browser.fetch(
            "/api/persona-rules/architect", {"model_id": name}, method="POST"
        )
        assert status == 200, body
        assert rules(browser)["architect"]["model_id"] == name
        status, records, _ = browser.fetch(
            "/api/audit/records?kind=settings&search=persona"
        )
        assert status == 200
        expected = {
            f"Added a persona rule for Architect: {name}",
            f"Changed the persona rule for Architect to {name}",
        }
        assert any(
            row["what"] in expected and row["who"] == "first-admin"
            for row in records["records"]
        ), records

        # RULE-LIVE-02: the model can't be removed while the rule uses it.
        status, body, _ = browser.fetch(
            f"/api/models/{name}/setup", {}, method="DELETE"
        )
        assert status == 409 and body["in_use"]["persona_rules"] == ["Architect"], body

        # RULE-LIVE-03: put the rule back as it was, then removal works.
        status, body, _ = browser.fetch(
            "/api/persona-rules/architect", {"model_id": original}, method="POST"
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
                "/api/persona-rules/architect", {"model_id": original}, method="POST"
            )
            browser.fetch(f"/api/models/{name}/setup", {}, method="DELETE")
        if not settings_audit:
            browser.fetch(
                "/api/audit/options/settings", {"enabled": False}, method="PUT"
            )
