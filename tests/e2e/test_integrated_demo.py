"""Exercise the complete protected Docker demo with a real local Qwen model."""

import json
import sys
from datetime import datetime, timezone

from reporting import report_path
from test_accounts import BASE, Browser, RUNTIME


MODEL = "demo-qwen"
RUNNER = "http://qwen:8080"
UPSTREAM = "qwen2.5-coder:0.5b"
REPORT = report_path("2026-10-09-integrated-demo.json")


def main():
    cases = []

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    anonymous = Browser()
    anonymous_status, _, _ = anonymous.fetch("/api/models")
    admin = Browser()
    login_status, url, page, sign_in_url, _ = admin.login(
        "first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    record("DEMO-01", anonymous_status == 401 and sign_in_url == BASE + "/sign-in" and
           login_status == 200 and url == BASE + "/",
           {"anonymous_api_status": anonymous_status, "sign_in_url": sign_in_url,
            "login_status": login_status})
    record("DEMO-02", 'id="add-dialog"' in page and 'id="add-class-choices"' in page and
           "Models and routing" in page,
           {"model_dialog_present": 'id="add-dialog"' in page,
            "approval_choices_present": 'id="add-class-choices"' in page})

    class_status, class_list, _ = admin.fetch("/api/data-classes")
    classes = {item["name"] for item in class_list.get("classes", [])}
    runner_status, discovery, _ = admin.fetch("/api/runners/models", {"address": RUNNER}, method="POST")
    record("DEMO-03", class_status == 200 and {"Public", "Internal"} <= classes and
           runner_status == 200 and UPSTREAM in discovery.get("models", []),
           {"class_status": class_status, "classes": sorted(classes),
            "runner_status": runner_status, "models": discovery.get("models", [])})

    register_status, register, _ = admin.fetch("/api/models", {
        "name": MODEL, "model": UPSTREAM, "source": "runner", "address": RUNNER,
        "approved_classes": ["Public", "Internal"]}, method="POST")
    listed_status, listing, _ = admin.fetch("/api/models")
    item = next((entry for entry in listing.get("models", []) if entry["id"] == MODEL), {})
    setup_status = None
    if register_status == 200 and item and not item.get("approved"):
        setup_status, _, _ = admin.fetch(f"/api/models/{MODEL}/setup", {
            "key_choice": "none", "approved_classes": ["Public", "Internal"]}, method="POST")
        listed_status, listing, _ = admin.fetch("/api/models")
        item = next((entry for entry in listing.get("models", []) if entry["id"] == MODEL), {})
    record("DEMO-04", register_status == 200 and listed_status == 200 and
           item.get("approved") is True and
           set(item.get("approved_classes", [])) == {"Public", "Internal"} and
           item.get("upstream_model") == UPSTREAM,
           {"register_status": register_status, "existing": register.get("existing"),
            "setup_status": setup_status, "model": item})

    ask_status, answer, _ = admin.fetch("/api/ask", {
        "model": MODEL, "prompt": "Reply with the word READY."}, method="POST")
    content = answer.get("answer", "") if isinstance(answer, dict) else ""
    record("DEMO-05", ask_status == 200 and bool(content.strip()) and content != "mock answer" and
           answer.get("model") == MODEL,
           {"ask_status": ask_status, "model": answer.get("model"),
            "answer_excerpt": content[:120]})

    with admin.opener.open(BASE + "/sign-out", timeout=15) as response:
        response.read()
    after_signout, _, _ = admin.fetch("/api/models")
    record("DEMO-06", after_signout == 401,
           {"model_api_after_signout": after_signout})

    result = {"suite": "Protected Docker admin to Qwen journey",
              "time_utc": datetime.now(timezone.utc).isoformat(),
              "cases": cases, "passed": sum(item["verdict"] == "pass" for item in cases),
              "failed": sum(item["verdict"] == "fail" for item in cases)}
    REPORT.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{result['passed']} passed, {result['failed']} failed; {REPORT}")
    for item in cases:
        print(item["id"], item["verdict"], item["observed"])
    return int(result["failed"] != 0)


if __name__ == "__main__":
    sys.exit(main())
