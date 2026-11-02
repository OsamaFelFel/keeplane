"""Every Spec 002 scenario is mapped to cases that exist and are tested.

The map is the "Spec 002 scenarios" table in tests/e2e/self-hosting-cases.md.
The plain-English cases are in self-hosting-scenario-map-cases.md.
"""

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
MAP = TESTS / "e2e/self-hosting-cases.md"
HEADING = "## Spec 002 scenarios (ST1–ST5)"

# The scenario names in Spec 002 (product/specs/002-self-hosting.md).
SCENARIOS = {
    ("ST1", "Install on the isolated network"),
    ("ST2", "The install may pull from the registry"),
    ("ST2", "Runs where only the models are reachable"),
    ("ST2", "The web UI loads from inside"),
    ("ST3", "A local model works like a cloud one"),
    ("ST3", "The managed gateway always requires keys"),
    ("ST4", "One gateway copy stops"),
    ("ST5", "We already run the gateway"),
}
# Scenarios not proven yet, each with the run that is still missing. The
# table's cell starts "Not proven yet:" and says the same.
NOT_PROVEN = {
    ("ST1", "Install on the isolated network"): (
        "No install has run on an isolated network (task 002-03)."
    ),
    ("ST2", "The install may pull from the registry"): (
        "No install has run through temporary registry access that was then "
        "closed (task 002-03)."
    ),
    ("ST2", "Runs where only the models are reachable"): (
        "No install has run with only model endpoints reachable; browser and "
        "device sign-in, the real coding runtime and the gateway image have "
        "not run under the outbound guard (task 002-03)."
    ),
    ("ST4", "One gateway copy stops"): (
        "No live run has stopped a gateway copy since the copies became a "
        "StatefulSet (keeplane #180; tasks 002-02 and 002-04)."
    ),
}
# Catalogs whose cases only render the chart. They can support a scenario but
# never prove one alone: a proven row must also name a case from elsewhere.
RENDER_ONLY = {"SHAPE", "NETPOL", "PKG"}
CASE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z]+)*-\d+\b")
# The catalog each case prefix belongs to, as the map's intro links them. A
# case counts only if its row is in its own catalog, so a row with the same ID
# in another catalog can't satisfy it.
CATALOGS = {
    "SHAPE": "integration/chart-installation-shape-cases.md",
    "NETPOL": "integration/chart-network-policies-cases.md",
    "PKG": "integration/chart-package-cases.md",
    "GW-KEY": "integration/gateway-policy-cases.md",
    "EGR": "unit/outbound-connection-cases.md",
    "OFF": "unit/ui-offline-assets-cases.md",
    "OFF-UI": "browser/offline-assets-cases.md",
    "K8S": "e2e/kubernetes-cases.md",
    "FULL": "e2e/full-product-edge-cases.md",
    "EXEDGE": "e2e/full-existing-edge-cases.md",
    "EXIST": "e2e/existing-gateway-cases.md",
}


def scenario_rows():
    text = MAP.read_text()
    assert HEADING in text, "The Spec 002 scenario table is missing"
    section = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and re.fullmatch(r"ST\d+", cells[0]):
            assert (cells[0], cells[1]) not in rows, f"{cells[:2]} is listed twice"
            rows[(cells[0], cells[1])] = cells[2]
    return rows


def source_text():
    paths = [
        path
        for pattern in ("*.py", "*.ts", "*.tsx", "*.mjs")
        for path in TESTS.rglob(pattern)
        if "node_modules" not in path.parts and path != Path(__file__)
    ]
    return "\n".join(path.read_text() for path in paths)


def is_tested(case, code):
    prefix, number = case.rsplit("-", 1)
    slug = prefix.lower().replace("-", "_")
    # A test function named after the case, possibly with neighbouring cases
    # (test_egr_01_02_...), or the case ID itself in a test's report or title.
    named = re.search(rf"\btest_{slug}(?:_\d+)*_{number}(?:_|\b)", code)
    return bool(named or re.search(rf"[\"'`\s]{re.escape(case)}\b", code))


def prefix_of(case):
    return case.rsplit("-", 1)[0]


def test_shm_01_every_spec_scenario_is_listed_once():
    assert set(scenario_rows()) == SCENARIOS
    assert set(NOT_PROVEN) <= SCENARIOS


def test_shm_02_proven_scenarios_name_cases_and_unproven_ones_say_why():
    for scenario, checked_by in scenario_rows().items():
        named = CASE.findall(checked_by)
        if scenario in NOT_PROVEN:
            assert NOT_PROVEN[scenario], f"{scenario} needs a reason"
            assert re.match(r"Not proven yet: \S", checked_by), scenario
            # It names the cases that come closest, so the gap is visible.
            assert named, f"{scenario} names no case"
        else:
            assert not checked_by.startswith("Not "), scenario
            assert named, scenario


def test_shm_03_a_render_check_never_proves_a_scenario_alone():
    for scenario, checked_by in scenario_rows().items():
        if scenario in NOT_PROVEN:
            continue
        prefixes = {prefix_of(case) for case in CASE.findall(checked_by)}
        assert prefixes - RENDER_ONLY, f"{scenario} is proven only by rendering"


def test_shm_04_every_named_case_has_a_row_in_its_own_catalog_and_a_test():
    code = source_text()
    named = {case for cell in scenario_rows().values() for case in CASE.findall(cell)}
    assert named
    for case in sorted(named):
        prefix = prefix_of(case)
        assert prefix in CATALOGS, f"{case} has no known catalog"
        catalog = (TESTS / CATALOGS[prefix]).read_text()
        assert re.search(
            rf"^\|\s*{re.escape(case)}\s*\|", catalog, re.MULTILINE
        ), f"{case} has no row in {CATALOGS[prefix]}"
        assert is_tested(case, code), f"{case} has no test"


def test_shm_05_the_map_links_every_catalog_it_names():
    intro = MAP.read_text().split(HEADING, 1)[1].split("| Story |", 1)[0]
    links = {
        (MAP.parent / target).resolve()
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", intro)
    }
    named = {
        prefix_of(case)
        for cell in scenario_rows().values()
        for case in CASE.findall(cell)
    }
    for prefix in sorted(named):
        assert (TESTS / CATALOGS[prefix]).resolve() in links, (
            f"{CATALOGS[prefix]} is not linked"
        )
