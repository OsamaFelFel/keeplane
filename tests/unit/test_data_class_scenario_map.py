"""Every Spec 005 scenario is mapped to cases that exist and are tested.

The map is the "Spec 005 scenarios" table in tests/e2e/data-classes-cases.md.
The plain-English cases are in data-class-scenario-map-cases.md.
"""

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
MAP = TESTS / "e2e/data-classes-cases.md"
HEADING = "## Spec 005 scenarios (ST18, ST19, ST20)"

# The scenario names in Spec 005 (product/specs/005-data-classes.md). Two
# scenarios share the name "Off by default", so each is keyed by its story.
SCENARIOS = {
    ("ST18", "Off by default"),
    ("ST18", "Starter classes"),
    ("ST18", "Add a class"),
    ("ST18", "Change a class"),
    ("ST18", "A class in use"),
    ("ST19", "Set a class"),
    ("ST19", "Only approved models"),
    ("ST19", "The repo can't change it"),
    ("ST19", "No approved model is up"),
    ("ST19", "No class"),
    ("ST20", "Off by default"),
    ("ST20", "What detection finds"),
    ("ST20", "Code isn't personal data"),
    ("ST20", "Detection holds a request"),
    ("ST20", "Detection fails"),
    ("ST20", "Choose the class"),
}
# Scenarios listed but not yet provable, each with its reason; none for now.
NOT_BUILT = {}
CASE = re.compile(r"\b[A-Z]+(?:-[A-Z]+)*-\d+\b")
# The catalogs each case prefix belongs to, as the map's intro paragraph links
# them. A case counts only if its row is in one of its own catalogs, so a row
# with the same ID in another catalog can't satisfy it. DC-UI cases are split
# between the browser cases and the React UI unit cases.
CATALOGS = {
    "CLASS": ("e2e/data-classes-cases.md",),
    "CLI-CLASS": ("unit/cli-signed-in-coding-cases.md",),
    "DC-UI": ("browser/data-classes-cases.md", "unit/ui/cases.md"),
    "DCA": ("integration/data-class-admin-cases.md",),
    "MC": ("integration/model-choice-cases.md",),
    "PCL-LIVE": ("e2e/project-classes-live-cases.md",),
    "PDL-LIVE": ("e2e/personal-data-live-cases.md",),
    "PD": ("unit/personal-data-detection-cases.md",),
    "PM": ("integration/personal-data-model-cases.md",),
    "PR": ("integration/personal-data-routing-cases.md",),
    "PRJ-UI": ("browser/projects-cases.md",),
    "RT": ("integration/task-routing-cases.md",),
}


def scenario_rows():
    text = MAP.read_text()
    assert HEADING in text, "The Spec 005 scenario table is missing"
    section = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith("ST"):
            assert (cells[0], cells[1]) not in rows, f"{cells[:2]} is listed twice"
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
    # (test_dca_01_02_...), or the case ID itself in a test's report, title or
    # the comment that opens it.
    named = re.search(rf"\btest_{slug}(?:_\d+)*_{number}(?:_|\b)", code)
    return bool(named or re.search(rf"[\"'`\s]{re.escape(case)}\b", code))


def test_dsm_01_every_spec_scenario_is_listed_once():
    assert set(scenario_rows()) == SCENARIOS
    assert set(NOT_BUILT) <= SCENARIOS


def test_dsm_02_built_scenarios_name_cases_and_unbuilt_ones_say_why():
    for scenario, checked_by in scenario_rows().items():
        if scenario in NOT_BUILT:
            assert NOT_BUILT[scenario], f"{scenario} needs a reason"
            assert checked_by.startswith("Not built yet"), scenario
        else:
            assert CASE.findall(checked_by), scenario


def test_dsm_03_every_named_case_has_a_row_in_its_own_catalog_and_a_test():
    code = source_text()
    named = {case for cell in scenario_rows().values() for case in CASE.findall(cell)}
    assert named
    for case in sorted(named):
        prefix = case.rsplit("-", 1)[0]
        assert prefix in CATALOGS, f"{case} has no known catalog"
        assert any(
            re.search(
                rf"^\|\s*{re.escape(case)}\b",
                (TESTS / catalog).read_text(),
                re.MULTILINE,
            )
            for catalog in CATALOGS[prefix]
        ), f"{case} has no row in {' or '.join(CATALOGS[prefix])}"
        assert is_tested(case, code), f"{case} has no test"


def test_dsm_04_the_map_links_every_catalog_it_names():
    intro = MAP.read_text().split(HEADING, 1)[1].split("| Story |", 1)[0]
    links = {
        (MAP.parent / target).resolve()
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", intro)
    }
    named = {
        case.rsplit("-", 1)[0]
        for cell in scenario_rows().values()
        for case in CASE.findall(cell)
    }
    for prefix in sorted(named - {"CLASS"}):
        for catalog in CATALOGS[prefix]:
            assert (TESTS / catalog).resolve() in links, f"{catalog} is not linked"
