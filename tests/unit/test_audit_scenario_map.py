"""Every Spec 006 scenario is mapped to cases that exist and are tested.

The map is the "Spec 006 scenarios" table in tests/e2e/audit-cases.md. The
plain-English cases are in audit-scenario-map-cases.md.
"""

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
MAP = TESTS / "e2e/audit-cases.md"
HEADING = "## Spec 006 scenarios (ST21, ST22)"

# The scenario names in Spec 006 (product/specs/006-audit.md).
SCENARIOS = {
    ("ST21", "After install"),
    ("ST21", "Settings changes"),
    ("ST21", "Held-back requests"),
    ("ST21", "Model answers"),
    ("ST21", "Break-glass sign-ins"),
    ("ST21", "One kind only"),
    ("ST22", "Find records"),
}
# Scenarios listed but not yet provable; none since task 006-02.
NOT_BUILT = set()
CASE = re.compile(r"\b[A-Z]+(?:-[A-Z]+)*-\d+\b")
# The catalog each case prefix belongs to, as the map's intro paragraph links
# them. A case counts only if its row is in its own catalog, so a row with the
# same ID in another catalog can't satisfy it.
CATALOGS = {
    "AS": "integration/audit-persistence-cases.md",
    "AU-UI": "browser/audit-cases.md",
    "AUD": "e2e/audit-cases.md",
    "BG": "e2e/audit-cases.md",
    "BGS": "integration/break-glass-sign-in-cases.md",
    "CL-INT": "integration/complexity-level-cases.md",
    "HR": "integration/held-request-record-cases.md",
    "MA": "integration/model-answer-record-cases.md",
    "SC": "integration/settings-change-record-cases.md",
}


def scenario_rows():
    text = MAP.read_text()
    assert HEADING in text, "The Spec 006 scenario table is missing"
    section = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith("ST"):
            rows[(cells[0], cells[1])] = cells[2]
    return rows


def source_text():
    paths = [
        path
        for pattern in ("*.py", "*.ts", "*.tsx")
        for path in TESTS.rglob(pattern)
        if "node_modules" not in path.parts and path != Path(__file__)
    ]
    return "\n".join(path.read_text() for path in paths)


def is_tested(case, code):
    prefix, number = case.rsplit("-", 1)
    slug = prefix.lower().replace("-", "_")
    # A test function named after the case, possibly with neighbouring cases
    # (test_as_01_02_...), or the case ID itself in a test's report or title.
    named = re.search(rf"\btest_{slug}(?:_\d+)*_{number}(?:_|\b)", code)
    return bool(named or re.search(rf"[\"'`\s]{re.escape(case)}\b", code))


def test_asm_01_every_spec_scenario_is_listed_once():
    rows = scenario_rows()
    assert set(rows) == SCENARIOS


def test_asm_02_built_scenarios_name_cases_and_unbuilt_ones_say_so():
    for scenario, checked_by in scenario_rows().items():
        if scenario in NOT_BUILT:
            assert checked_by.startswith("Not built yet"), scenario
        else:
            assert CASE.findall(checked_by), scenario


def test_asm_03_every_named_case_has_a_row_in_its_own_catalog_and_a_test():
    code = source_text()
    named = {case for cell in scenario_rows().values() for case in CASE.findall(cell)}
    assert named
    for case in sorted(named):
        prefix = case.rsplit("-", 1)[0]
        assert prefix in CATALOGS, f"{case} has no known catalog"
        catalog = (TESTS / CATALOGS[prefix]).read_text()
        assert re.search(
            rf"^\|\s*{re.escape(case)}\b", catalog, re.MULTILINE
        ), f"{case} has no row in {CATALOGS[prefix]}"
        assert is_tested(case, code), f"{case} has no test"
