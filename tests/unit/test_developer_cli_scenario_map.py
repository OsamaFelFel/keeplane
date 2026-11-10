"""Every Spec 009 scenario is mapped to cases that exist, are tested and run in CI.

The map is the "Spec 009 scenarios" table in tests/e2e/developer-cli-cases.md.
The plain-English cases are in developer-cli-scenario-map-cases.md.
"""

import ast
import re
from pathlib import Path

from tests.support.shards import shard_of

TESTS = Path(__file__).resolve().parents[1]
ROOT = TESTS.parent
MAP = TESTS / "e2e/developer-cli-cases.md"
HEADING = "## Spec 009 scenarios (ST29–ST31)"
CHECKS = ROOT / ".github/workflows/checks.yml"
LIVE_PREVIEW = ROOT / ".github/workflows/live-preview.yml"
JOURNEY = TESTS / "e2e/test_developer_journey.py"

# The scenario names in Spec 009 (product/specs/009-developer-cli.md).
SCENARIOS = {
    ("ST29", "Sign in through the browser"),
    ("ST29", "No browser on the machine"),
    ("ST29", "An admin signs in"),
    ("ST29", "Sign out"),
    ("ST29", "The sign-in has expired"),
    ("ST30", "Work in a repo"),
    ("ST30", "A repo not set up in Keeplane"),
    ("ST30", "Cloud models use API keys"),
    ("ST31", "My usage"),
    ("ST31", "A local model"),
    ("ST31", "Cost is an estimate"),
    ("ST31", "Only my own usage"),
}
# Scenarios not proven yet. Only a check CI runs on the current revision proves
# a scenario. The reason lives in the table only: its "Proven by" cell starts
# "Not proven yet:" and says what is missing before naming any case.
NOT_PROVEN = {
    ("ST30", "Cloud models use API keys"),
}
CASE = re.compile(r"\b[A-Z]+(?:-[A-Z]+)*-[A-Z]?\d+\b")
# The CI jobs that count as proof. "unit" and "integration" are the backend
# shards of checks.yml; the others are named jobs that run listed test files.
JOBS = {
    "cli-sign-in": CHECKS,
    "coding-runtime": CHECKS,
    "live-gateway": LIVE_PREVIEW,
}
# Each case prefix's catalog, the test file that runs it and the CI job that
# runs that file (None: CI doesn't run it). A case counts only if its row is in
# its own catalog and its own test file names it, so a row or test with the
# same ID elsewhere can't satisfy it.
SOURCES = {
    "DEV": (
        "e2e/developer-journey-cases.md",
        "e2e/test_developer_journey.py",
        "live-gateway",
    ),
    "PSI-LIVE": (
        "e2e/preview-sign-in-live-cases.md",
        "e2e/test_preview_sign_in_live.py",
        "live-gateway",
    ),
    "ADM-INT": (
        "integration/cli-admin-sign-in-cases.md",
        "integration/test_cli_admin_sign_in.py",
        "cli-sign-in",
    ),
    "EXP-INT": (
        "integration/cli-sign-in-again-cases.md",
        "integration/test_cli_sign_in_again.py",
        "cli-sign-in",
    ),
    "NB": ("unit/cli-no-browser-cases.md", "unit/test_cli_no_browser.py", "unit"),
    "EXP": (
        "unit/cli-sign-in-again-cases.md",
        "unit/test_cli_sign_in_again.py",
        "unit",
    ),
    "OUT": (
        "unit/cli-sign-in-again-cases.md",
        "unit/test_cli_sign_in_again.py",
        "unit",
    ),
    "KEY": (
        "unit/cli-runtime-settings-cases.md",
        "unit/test_cli_runtime_settings.py",
        "unit",
    ),
    "RPJ": (
        "integration/cli-repo-project-cases.md",
        "integration/test_cli_repo_projects.py",
        "integration",
    ),
    "PK": (
        "integration/runtime-provider-key-cases.md",
        "integration/test_runtime_provider_keys.py",
        "integration",
    ),
    "MC": (
        "integration/model-choice-cases.md",
        "integration/test_model_choice.py",
        "integration",
    ),
    "USE": ("unit/cli-usage-cases.md", "unit/test_cli_usage.py", "unit"),
    "DU": (
        "integration/developer-usage-cases.md",
        "integration/test_developer_usage.py",
        "integration",
    ),
    "DU-C": (
        "integration/developer-usage-cases.md",
        "integration/test_usage_cost.py",
        "integration",
    ),
}
# Cases whose prefix shares a catalog family but lives elsewhere: KEY-09 runs
# with the pinned runtime, unlike the KEY unit cases.
CASE_SOURCES = {
    "KEY-09": ("e2e/cli-runtime-cases.md", "e2e/test_cli_runtime.py", "coding-runtime"),
}
UNRUN_MARKS = {"live", "optional"}


def prefix_of(case):
    # DU-C1 belongs to DU-C, DU-01 to DU.
    return re.sub(r"-?\d+$", "", case)


def source_of(case):
    if case in CASE_SOURCES:
        return CASE_SOURCES[case]
    assert prefix_of(case) in SOURCES, f"{case} has no known catalog"
    return SOURCES[prefix_of(case)]


def scenario_rows():
    text = MAP.read_text()
    assert HEADING in text, "The Spec 009 scenario table is missing"
    section = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.fullmatch(r"ST\d+", cells[0]):
            scenario = (cells[0], cells[1])
            assert scenario not in rows, f"{scenario} is listed twice"
            rows[scenario] = (cells[2], cells[3])
    return rows


def named_cases(cells=(0, 1)):
    return {
        case
        for row in scenario_rows().values()
        for index in cells
        for case in CASE.findall(row[index])
    }


def case_test_pattern(case):
    """A test function named after the case: test_nb_02_..., test_du_c1_...,
    or with neighbouring cases (test_adm_int_01_02_...)."""
    prefix, number = case.rsplit("-", 1)
    slug = prefix.lower().replace("-", "_")
    return rf"\btest_{slug}(?:_\d+)*_{number.lower()}(?:_|\b)"


def is_tested(case, code):
    # A test named after the case, or its ID in a test's report or title.
    named = re.search(case_test_pattern(case), code)
    return bool(named or re.search(rf"[\"'`\s(]{re.escape(case)}\b", code))


def marks(decorators):
    found = set()
    for node in decorators:
        for part in ast.walk(node):
            if (
                isinstance(part, ast.Attribute)
                and part.attr in UNRUN_MARKS
                and isinstance(part.value, ast.Attribute)
                and part.value.attr == "mark"
            ):
                found.add(part.attr)
    return found


def shard_runs(case, path):
    """The test named after the case runs in the default backend selection.

    The shards run `pytest tests/unit tests/integration --shard <name>`, which
    pytest.ini limits to `not live`; checks marked live or optional need their
    own job, so a test with either mark never counts as run by the shards.
    """
    tree = ast.parse(path.read_text())
    module = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in node.targets
        ):
            module |= marks([node.value])
    tests = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and re.match(case_test_pattern(case), node.name)
    ]
    assert tests, f"{case} has no test named after it in {path.name}"
    return all(not (module | marks(node.decorator_list)) for node in tests)


def job_section(workflow, job):
    text = workflow.read_text()
    match = re.search(
        rf"^  {re.escape(job)}:\n(.*?)(?=^  [\w-]+:\n|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"{workflow.name} has no {job} job"
    return match.group(1)


def runs_in_ci(case):
    _, test_file, job = source_of(case)
    path = TESTS / test_file
    if job is None:
        return False
    if job in ("unit", "integration"):
        shard = shard_of(path)
        assert "pytest tests/unit tests/integration --shard" in CHECKS.read_text()
        return bool(shard and shard.startswith(job) and shard_runs(case, path))
    section = job_section(JOBS[job], job)
    # The job runs the file and fails when a case is skipped or doesn't run.
    return f"tests/{test_file}" in section and "skipped" in section


def journey_cases():
    tree = ast.parse(JOURNEY.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CASES"
            for target in node.targets
        ):
            return set(ast.literal_eval(node.value))
    raise AssertionError("The developer journey declares no CASES")


def test_dcsm_01_every_spec_scenario_is_listed_once():
    assert set(scenario_rows()) == SCENARIOS
    assert NOT_PROVEN <= SCENARIOS


def test_dcsm_02_proven_scenarios_name_cases_and_unproven_ones_say_why():
    for scenario, (proven_by, closest) in scenario_rows().items():
        assert closest, f"{scenario} has an empty closest-evidence cell"
        if scenario in NOT_PROVEN:
            reason = re.match(r"Not proven yet: (.*)", proven_by)
            assert reason, f"{scenario} must start with 'Not proven yet:'"
            # The reason comes before the first case it names, in words.
            before_cases = CASE.split(reason.group(1), 1)[0]
            assert len(re.findall(r"[a-z]+", before_cases)) >= 5, (
                f"{scenario} gives no reason before naming cases"
            )
            # It names the cases that come closest, so the gap is visible.
            assert CASE.findall(closest), f"{scenario} names no closest evidence"
        else:
            assert not proven_by.startswith("Not "), scenario
            assert CASE.findall(proven_by), f"{scenario} names no case"


def test_dcsm_03_every_proof_is_a_check_ci_runs_on_this_revision():
    for scenario, (proven_by, _) in scenario_rows().items():
        for case in CASE.findall(proven_by):
            assert runs_in_ci(case), (
                f"{scenario} names {case}, which CI doesn't run; "
                "move it to closest evidence"
            )


def test_dcsm_04_every_named_case_has_a_row_in_its_own_catalog_and_a_test():
    named = named_cases()
    assert named
    for case in sorted(named):
        catalog, test_file, _ = source_of(case)
        text = (TESTS / catalog).read_text()
        # A table row or a list item that starts with the case, bold or not.
        assert re.search(
            rf"^(?:\|\s*|-\s+)(?:\*\*)?{re.escape(case)}\b", text, re.MULTILINE
        ), f"{case} has no row in {catalog}"
        assert is_tested(case, (TESTS / test_file).read_text()), (
            f"{case} has no test in {test_file}"
        )


def test_dcsm_05_the_map_links_every_catalog_it_names():
    intro = MAP.read_text().split(HEADING, 1)[1].split("| Story |", 1)[0]
    links = {
        (MAP.parent / target).resolve()
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", intro)
    }
    for case in sorted(named_cases()):
        catalog = source_of(case)[0]
        assert (TESTS / catalog).resolve() in links, f"{catalog} is not linked"


def test_dcsm_06_journey_cases_are_ones_the_journey_suite_runs():
    # A DEV case counts only once the journey suite declares it, whatever
    # other files mention it. The live-gateway job runs the suite and fails
    # when a declared case doesn't pass.
    declared = journey_cases()
    for case in sorted(case for case in named_cases() if prefix_of(case) == "DEV"):
        assert case in declared, f"{case} isn't in the journey suite's CASES"
    assert runs_in_ci("DEV-01")


def test_dcsm_07_a_check_ci_does_not_run_never_counts(monkeypatch):
    # A test marked live or optional is never counted as run by the shards.
    monkeypatch.setitem(
        CASE_SOURCES,
        "ADM-INT-01",
        (
            "integration/cli-admin-sign-in-cases.md",
            "integration/test_cli_admin_sign_in.py",
            "integration",
        ),
    )
    assert not runs_in_ci("ADM-INT-01")
    # A file a job doesn't list is never counted as run by that job.
    monkeypatch.setitem(
        CASE_SOURCES,
        "PCLI-04",
        (
            "e2e/installed-personal-cli-cases.md",
            "e2e/test_installed_personal_cli.py",
            "cli-sign-in",
        ),
    )
    assert not runs_in_ci("PCLI-04")
    # A catalog with no CI job never counts.
    monkeypatch.setitem(
        CASE_SOURCES,
        "NB-02",
        ("unit/cli-no-browser-cases.md", "unit/test_cli_no_browser.py", None),
    )
    assert not runs_in_ci("NB-02")
