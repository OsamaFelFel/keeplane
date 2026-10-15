"""Require the complete declared case set from each migrated journey suite."""

import json
from pathlib import Path

# These are the existing regression case IDs, retained across the pytest move.
EXPECTED_CASES = {
    "test_postgres_accounts": "PGAPI-01 PGAPI-02 PGAPI-03 PGAPI-04 PGAPI-05 PGAPI-06 PGAPI-07 PGAPI-08 PGAPI-09 PGAPI-10 PGAPI-11 PGAPI-12 PGAPI-13 PGAPI-14 PGAPI-15",
    "test_account_security": "ACCT-24 ACCT-25 ACCT-26 ACCT-27",
    "test_accounts": "ACCT-01 ACCT-02 ACCT-03 ACCT-04 ACCT-05 ACCT-06 ACCT-07 ACCT-08 ACCT-09 ACCT-10 ACCT-11 ACCT-12 ACCT-13 ACCT-14 ACCT-15 ACCT-16 ACCT-17 ACCT-18 ACCT-19 ACCT-20 ACCT-23",
    "test_audit": "AUD-01 AUD-02 AUD-05 AUD-03 AUD-04 AUD-06 AUD-08 AUD-09 AUD-07",
    "test_break_glass_audit": "BG-07 BG-08 BG-09",
    "test_chart_package": "PKG-01 PKG-02 PKG-03 PKG-04 PKG-05 PKG-06 PKG-07 PKG-08",
    "test_cloud_add": "CADD-01 CADD-02 CADD-03 CADD-04 CADD-05 CADD-06 CADD-07 CADD-08 CADD-09",
    "test_cloud_listing": "CLOUD-01 CLOUD-02 CLOUD-03 CLOUD-04",
    "test_csrf": "CSRF-01 CSRF-02 CSRF-03 CSRF-04 CSRF-05 CSRF-06 CSRF-07 CSRF-08",
    "test_data_classes": "CLASS-00 CLASS-10 CLASS-01 CLASS-09 CLASS-02 CLASS-03 CLASS-04 CLASS-05 CLASS-06 CLASS-08 CLASS-07",
    "test_existing_gateway_live": "EXIST-01 EXIST-02 EXIST-03 EXIST-04",
    "test_existing_gateway_preflight": "K8S-10 K8S-11 K8S-12 K8S-13",
    "test_gateway_down": "K8S-08 K8S-09",
    "test_gateway_preflight_read_retry": "K8S-14 K8S-15 K8S-16",
    "test_gateway_secret_rotation": "GSECRET-05 GSECRET-06 GSECRET-07 GSECRET-08 GSECRET-09",
    "test_integrated_demo": "DEMO-01 DEMO-02 DEMO-03 DEMO-04 DEMO-05 DEMO-06",
    "test_key_rotation": "ROT-01 ROT-02 ROT-03 ROT-04 ROT-05",
    "test_kind": "K8S-01 K8S-02 K8S-03 K8S-04 K8S-07 K8S-05 K8S-17 K8S-06",
    "test_local": "LOCAL-01 LOCAL-02 LOCAL-03 LOCAL-04 LOCAL-05 LOCAL-08 LOCAL-11",
    "test_management_retry": "MGMT-01 MGMT-02 MGMT-03",
    "test_model_add": "ADD-01 ADD-02 ADD-03 ADD-04 ADD-05 ADD-06 ADD-07 ADD-08",
    "test_model_approval": "MODEL-01 MODEL-02 MODEL-03 MODEL-10 MODEL-04 MODEL-05 MODEL-06 MODEL-07 MODEL-08 MODEL-09",
    "test_model_edit": "EDIT-01 EDIT-02 EDIT-03 EDIT-04 EDIT-05",
    "test_model_removal": "REMOVE-01 REMOVE-02 REMOVE-03 REMOVE-04 REMOVE-05 REMOVE-06 REMOVE-07 REMOVE-08",
    "test_model_replacement": "REPLACE-01 REPLACE-02 REPLACE-03 REPLACE-04 REPLACE-05",
    "test_model_runtime": "LOCAL-19 LOCAL-20",
    "test_postgres_chart": "PGCHART-01 PGCHART-02 PGCHART-03 PGCHART-04 PGCHART-05 PGCHART-06",
    "test_preview_parity": "PARITY-01 PARITY-02",
    "test_qwen": "LOCAL-07 LOCAL-09",
    "test_runner_flow": "LOCAL-23 LOCAL-21 LOCAL-24 LOCAL-21-ADD LOCAL-22",
    "test_stack_lock": "LOCK-01 LOCK-02 LOCK-03 LOCK-04 LOCK-05",
}


def verify_cases(file, stdout, report_path):
    path = Path(report_path)
    report = None
    if path.is_file():
        report = json.loads(path.read_text())
    else:
        decoder = json.JSONDecoder()
        for index, character in enumerate(stdout):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(stdout[index:])
            except ValueError:
                continue
            if isinstance(candidate, dict) and (
                "cases" in candidate or "results" in candidate
            ):
                report = candidate
                break
    assert report is not None, "The suite did not emit its case report"
    rows = report.get("cases", report.get("results", []))
    actual = [row.get("id", row.get("case")) for row in rows]
    expected = EXPECTED_CASES[Path(file).stem].split()
    assert len(actual) == len(expected) and set(actual) == set(expected), (
        "Incomplete case set",
        sorted(set(expected) - set(actual)),
        sorted(set(actual) - set(expected)),
    )
    assert all(row["verdict"] == "pass" for row in rows)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
