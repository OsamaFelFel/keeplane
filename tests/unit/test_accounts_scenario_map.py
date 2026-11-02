"""Every Spec 003 scenario is mapped to cases that exist and are tested.

The map is the "Spec 003 scenarios" table in tests/e2e/accounts-cases.md. The
plain-English cases are in accounts-scenario-map-cases.md.
"""

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
MAP = TESTS / "e2e/accounts-cases.md"
HEADING = "## Spec 003 scenarios (ST6–ST8, ST28)"

# The scenario names in Spec 003 (product/specs/003-accounts.md).
SCENARIOS = {
    ("ST6", "An admin signs in"),
    ("ST6", "A developer opens the web UI"),
    ("ST6", "Sign out"),
    ("ST6", "No single sign-on yet"),
    ("ST6", "Single sign-on connected"),
    ("ST7", "First sign-in after install"),
    ("ST7", "The break-glass admin in Users"),
    ("ST8", "Create a user with a role"),
    ("ST8", "Developer by default"),
    ("ST8", "No answer"),
    ("ST8", "Check finds the user"),
    ("ST8", "Check doesn't find the user"),
    ("ST8", "Sent twice"),
    ("ST8", "Find a user"),
    ("ST8", "No self sign-up"),
    ("ST28", "Change a role"),
    ("ST28", "The break-glass admin"),
}
# Scenarios not yet provable, and why. The table's cell says the same.
NOT_BUILT = {
    # No single sign-on provider can be connected until Spec 011 is handed
    # off (task 003-04). The sign-in screen's option is tested on its own.
    ("ST6", "Single sign-on connected"),
}
CASE = re.compile(r"\b[A-Z]+(?:-[A-Z]+)*-\d+\b")
# A range of cases with one prefix, such as "UI-ROLE-04 to UI-ROLE-09".
RANGE = re.compile(r"\b([A-Z]+(?:-[A-Z]+)*)-(\d+) to \1-(\d+)\b")
# The catalog each case prefix belongs to, as the map's intro links them. A
# case counts only if its row is in its own catalog, so a row with the same ID
# in another catalog can't satisfy it.
CATALOGS = {
    "ACCT": "e2e/accounts-cases.md",
    "LA": "integration/local-accounts-cases.md",
    "UI": "unit/ui/cases.md",
    "UI-SIGN": "unit/ui/cases.md",
    "UI-USERS": "unit/ui/cases.md",
    "UI-ROLE": "unit/ui/cases.md",
    "BR": "browser/users-cases.md",
    "BSEC": "browser/security-cases.md",
}


def scenario_rows():
    text = MAP.read_text()
    assert HEADING in text, "The Spec 003 scenario table is missing"
    section = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and re.fullmatch(r"ST\d+", cells[0]):
            rows.append(((cells[0], cells[1]), cells[2]))
    return rows


def named_cases(cell):
    """Every case a cell names, with each range expanded to all its cases."""
    cases = set(CASE.findall(cell))
    for prefix, first, last in RANGE.findall(cell):
        assert int(first) < int(last), f"{prefix}-{first} to {prefix}-{last}"
        width = len(first)
        cases.update(
            f"{prefix}-{number:0{width}d}"
            for number in range(int(first), int(last) + 1)
        )
    return cases


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
    # (test_la_01_02_...), or the case ID itself in a test's report or title.
    named = re.search(rf"\btest_{slug}(?:_\d+)*_{number}(?:_|\b)", code)
    return bool(named or re.search(rf"[\"'`\s(]{re.escape(case)}\b", code))


def has_row(case, catalog):
    # A table row that starts with the case, or a list item that does.
    return re.search(rf"^(?:\|\s*|-\s+){re.escape(case)}\b", catalog, re.MULTILINE)


def test_acsm_01_every_spec_scenario_is_listed_once():
    rows = scenario_rows()
    names = [scenario for scenario, _ in rows]
    assert len(names) == len(set(names)), "A scenario is listed twice"
    assert set(names) == SCENARIOS


def test_acsm_02_built_scenarios_name_cases_and_unbuilt_ones_say_why():
    assert NOT_BUILT <= SCENARIOS
    for scenario, checked_by in scenario_rows():
        if scenario in NOT_BUILT:
            assert re.match(r"Not built yet: \S", checked_by), scenario
        else:
            assert not checked_by.startswith("Not built yet"), scenario
            assert named_cases(checked_by), scenario


def test_acsm_03_every_named_case_has_a_row_in_its_own_catalog_and_a_test():
    code = source_text()
    named = {case for _, cell in scenario_rows() for case in named_cases(cell)}
    assert named
    for case in sorted(named):
        prefix = case.rsplit("-", 1)[0]
        assert prefix in CATALOGS, f"{case} has no known catalog"
        catalog = (TESTS / CATALOGS[prefix]).read_text()
        assert has_row(case, catalog), f"{case} has no row in {CATALOGS[prefix]}"
        assert is_tested(case, code), f"{case} has no test"


def test_acsm_04_a_range_names_every_case_inside_it():
    cell = "UI-ROLE-04 to UI-ROLE-06, BR-17"
    assert named_cases(cell) == {"UI-ROLE-04", "UI-ROLE-05", "UI-ROLE-06", "BR-17"}
