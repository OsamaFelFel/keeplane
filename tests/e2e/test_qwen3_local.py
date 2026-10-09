"""Leave a verified Qwen3 4B model available in the protected local preview."""

import json
import sys
from datetime import datetime, timezone

from reporting import report_path
from test_accounts import Browser, RUNTIME


MODEL = "qwen3-4b-instruct"
ADDRESS = "http://host.docker.internal:14424"
REPORT = report_path("2026-10-09-qwen3-local.json")


def main():
    browser = Browser()
    browser.login("first-admin", (RUNTIME / "first-admin-password").read_text().strip())
    cases = []

    def record(identifier, passed, observed):
        cases.append({"id": identifier, "verdict": "pass" if passed else "fail",
                      "observed": observed})

    discover_status, discovery, _ = browser.fetch("/api/runners/models",
                                                   {"address": ADDRESS}, method="POST")
    active = discovery.get("runtime", {}).get(MODEL, {}).get("active_context_tokens")
    record("Q3-01", discover_status == 200 and MODEL in discovery.get("models", [])
           and active == 12288,
           {"status": discover_status, "model_found": MODEL in discovery.get("models", []),
            "active_context_tokens": active, "error": discovery.get("error")})

    if discover_status == 200:
        add_status, added, _ = browser.fetch("/api/models", {
            "name": MODEL, "model": MODEL, "source": "runner", "address": ADDRESS,
            "approved_classes": ["Public"]}, method="POST")
        list_status, listing, _ = browser.fetch("/api/models")
        row = next((item for item in listing.get("models", []) if item.get("id") == MODEL), None)
        record("Q3-02", add_status == 200 and list_status == 200 and
               row is not None and row.get("approved") and
               "Public" in row.get("approved_classes", []),
               {"add_status": add_status, "list_status": list_status,
                "approved": row.get("approved") if row else None,
                "classes": row.get("approved_classes") if row else None,
                "error": added.get("error")})
        ask_status, answer, _ = browser.fetch("/api/ask", {
            "model": MODEL, "prompt": "Reply OK."}, method="POST")
        content = answer.get("answer", "")
        record("Q3-03", ask_status == 200 and isinstance(content, str) and bool(content.strip()),
               {"status": ask_status, "answer_excerpt": content[:120] if isinstance(content, str) else "",
                "error": answer.get("error")})

    report = {"suite": "Qwen3 4B local runner in protected Docker preview",
              "time_utc": datetime.now(timezone.utc).isoformat(), "cases": cases,
              "passed": sum(item["verdict"] == "pass" for item in cases),
              "failed": sum(item["verdict"] == "fail" for item in cases)}
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['passed']} passed, {report['failed']} failed; {REPORT}")
    return int(report["failed"] > 0)


if __name__ == "__main__":
    sys.exit(main())
