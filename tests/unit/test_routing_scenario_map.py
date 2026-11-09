"""Every Spec 004 scenario is mapped to cases that exist and are tested.

The map is the "Spec 004 scenarios" table in models-routing-cases.md. The
plain-English cases are in routing-scenario-map-cases.md.
"""

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
MAP = TESTS / "unit/models-routing-cases.md"
HEADING = "## Spec 004 scenarios (ST10–ST17, ST23–ST27)"

# The scenario names in Spec 004 (product/specs/004-models-and-routing.md).
SCENARIOS = {
    ("ST10", "Add a cloud model"),
    ("ST10", "Data classes are off"),
    ("ST10", "The customer runs its own gateway"),
    ("ST10", "Add a model from a local runner"),
    ("ST10", "The model doesn't answer"),
    ("ST10", "The gateway doesn't register the model"),
    ("ST10", "Each developer adds their own key"),
    ("ST10", "Already added"),
    ("ST11", "A shared key"),
    ("ST11", "See my keys"),
    ("ST11", "Add my own key"),
    ("ST11", "Never on the developer's machine"),
    ("ST11", "Replace or remove my key"),
    ("ST11", "A refused key"),
    ("ST11", "No key yet"),
    ("ST12", "No models yet"),
    ("ST13", "Keeplane's picks"),
    ("ST13", "How Keeplane picks"),
    ("ST13", "Context window not known"),
    ("ST13", "Change a pick"),
    ("ST13", "Go back to Keeplane's pick"),
    ("ST14", "Route by complexity"),
    ("ST15", "Add a persona rule"),
    ("ST15", "The rule applies"),
    ("ST16", "A model is down"),
    ("ST16", "The model answers on a retry"),
    ("ST16", "A task too big for the model"),
    ("ST16", "Down, and no other model allowed"),
    ("ST16", "Too big, and no other model allowed"),
    ("ST17", "See the model"),
    ("ST17", "Switch the model"),
    ("ST17", "My switch beats Keeplane's picks"),
    ("ST23", "Edit a model"),
    ("ST23", "Keep the shared key"),
    ("ST23", "Remove a model"),
    ("ST23", "A model in use"),
    ("ST23", "Keeplane's own pick"),
    ("ST23", "A model added outside Keeplane"),
    ("ST24", "Listed but unused"),
    ("ST24", "Set it up"),
    ("ST24", "Set it up with data classes off"),
    ("ST25", "Loading"),
    ("ST25", "The gateway isn't answering"),
    ("ST25", "No gateway name"),
    ("ST26", "Request settings pass through"),
    ("ST26", "The runner is left alone"),
    ("ST27", "Key count"),
}
# Scenarios not yet provable, and why. The table's cell says the same.
NOT_BUILT = {
    # Judging a task's complexity waits for task 004-03's router choice.
    ("ST14", "Route by complexity"),
    # The Developer CLI waits for Spec 009 (governance issue #28).
    ("ST17", "See the model"),
    ("ST17", "Switch the model"),
    # The server's order is built; the CLI switch waits for Spec 009 too.
    ("ST17", "My switch beats Keeplane's picks"),
}
CASE = re.compile(r"\b[A-Z]+(?:-[A-Z]+)*-\d+\b")
# The catalog each case prefix belongs to, as the map's intro links them. A
# case counts only if its row is in its own catalog, so a row with the same ID
# in another catalog can't satisfy it.
CATALOGS = {
    "MRS": "unit/models-routing-cases.md",
    "MOD-UI": "unit/ui/cases.md",
    "CL-UI": "unit/ui/cases.md",
    "PR-UI": "unit/ui/cases.md",
    "MO-UI": "browser/models-cases.md",
    "ML": "unit/model-listing-cases.md",
    "MR": "unit/model-removal-cases.md",
    "GC": "unit/gateway-copy-cases.md",
    "PR": "unit/persona-rule-cases.md",
    "CODE": "unit/cli-signed-in-coding-cases.md",
    "KC": "unit/cli-provider-key-command-cases.md",
    "REQ": "unit/cli-request-settings-cases.md",
    "RK": "unit/cli-refused-key-cases.md",
    "RETRY": "unit/runtime-config-cases.md",
    "CL": "integration/complexity-level-cases.md",
    "CL-INT": "integration/complexity-level-cases.md",
    "PR-INT": "integration/persona-rule-cases.md",
    "RT": "integration/task-routing-cases.md",
    "MC": "integration/model-choice-cases.md",
    "ALT": "integration/model-alternatives-cases.md",
    "OUT": "integration/native-runtime-outage-cases.md",
    "PROTO": "integration/native-runtime-protocol-cases.md",
    "CAT": "integration/runtime-catalog-cases.md",
    "KL": "integration/runtime-key-list-cases.md",
    "PK": "integration/runtime-provider-key-cases.md",
    "KR": "integration/developer-key-recheck-cases.md",
    "MP": "integration/model-policy-cases.md",
    "RK-INT": "integration/cli-refused-key-cases.md",
    "PMR": "integration/personal-model-registration-cases.md",
    "DK-COUNT": "integration/personal-key-count-cases.md",
    "MA": "integration/model-answer-record-cases.md",
    "MODEL": "e2e/model-approval-cases.md",
    "EDIT": "e2e/model-edit-cases.md",
    "REMOVE": "e2e/model-removal-cases.md",
    "REPLACE": "e2e/model-replacement-cases.md",
    "CADD": "e2e/cloud-add-cases.md",
    "EXIST": "e2e/existing-gateway-cases.md",
    "LEVEL-LIVE": "e2e/complexity-levels-cases.md",
    "RULE-LIVE": "e2e/persona-rules-cases.md",
}


def scenario_rows():
    text = MAP.read_text()
    assert HEADING in text, "The Spec 004 scenario table is missing"
    section = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and re.fullmatch(r"ST\d+", cells[0]):
            rows.append(((cells[0], cells[1]), cells[2]))
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
    # (test_mrs_01_02_...), or the case ID itself in a test's report or title.
    named = re.search(rf"\btest_{slug}(?:_\d+)*_{number}(?:_|\b)", code)
    return bool(named or re.search(rf"[\"'`\s]{re.escape(case)}\b", code))


def has_row(case, catalog):
    # A table row that starts with the case, or a list item that does.
    return re.search(
        rf"^(?:\|\s*|-\s+){re.escape(case)}\b", catalog, re.MULTILINE
    )


def test_rsm_01_every_spec_scenario_is_listed_once():
    rows = scenario_rows()
    names = [scenario for scenario, _ in rows]
    assert len(names) == len(set(names)), "A scenario is listed twice"
    assert set(names) == SCENARIOS


def test_rsm_02_built_scenarios_name_cases_and_unbuilt_ones_say_why():
    assert NOT_BUILT <= SCENARIOS
    for scenario, checked_by in scenario_rows():
        if scenario in NOT_BUILT:
            assert re.match(r"Not built yet: \S", checked_by), scenario
        else:
            assert not checked_by.startswith("Not built yet"), scenario
            assert CASE.findall(checked_by), scenario


def test_rsm_03_every_named_case_has_a_row_in_its_own_catalog_and_a_test():
    code = source_text()
    named = {case for _, cell in scenario_rows() for case in CASE.findall(cell)}
    assert named
    for case in sorted(named):
        prefix = case.rsplit("-", 1)[0]
        assert prefix in CATALOGS, f"{case} has no known catalog"
        catalog = (TESTS / CATALOGS[prefix]).read_text()
        assert has_row(case, catalog), f"{case} has no row in {CATALOGS[prefix]}"
        assert is_tested(case, code), f"{case} has no test"
