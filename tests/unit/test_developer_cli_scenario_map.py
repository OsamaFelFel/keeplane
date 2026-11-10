"""Every Spec 009 scenario is mapped to cases that exist, are tested and run in CI.

The map is the "Spec 009 scenarios" table in tests/e2e/developer-cli-cases.md.
The plain-English cases are in developer-cli-scenario-map-cases.md.
"""

import ast
import re
from pathlib import Path

import pytest

from tests.support.shards import shard_of

TESTS = Path(__file__).resolve().parents[1]
ROOT = TESTS.parent
MAP = TESTS / "e2e/developer-cli-cases.md"
HEADING = "## Spec 009 scenarios (ST29–ST31)"
CHECKS = ROOT / ".github/workflows/checks.yml"
LIVE_PREVIEW = ROOT / ".github/workflows/live-preview.yml"
KUBERNETES_LIVE = ROOT / ".github/workflows/kubernetes-live.yml"

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
# None today: DEV-10 proves ST30 "Cloud models use API keys".
NOT_PROVEN = set()
CASE = re.compile(r"\b[A-Z]+(?:-[A-Z]+)*-[A-Z]?\d+\b")
# The CI jobs that count as proof. "unit" and "integration" are the backend
# shards of checks.yml; the others are named jobs that run listed test files.
JOBS = {
    "cli-sign-in": CHECKS,
    "coding-runtime": CHECKS,
    "live-gateway": LIVE_PREVIEW,
    "release-journey": CHECKS,
    "kind": KUBERNETES_LIVE,
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
    "DJR": (
        "e2e/developer-journey-release-cases.md",
        "e2e/test_developer_journey_release.py",
        "release-journey",
    ),
    "PSI-LIVE": (
        "e2e/preview-sign-in-live-cases.md",
        "e2e/test_preview_sign_in_live.py",
        "live-gateway",
    ),
    "KDEV": (
        "e2e/kubernetes-developer-cases.md",
        "e2e/test_kind_protected.py",
        "kind",
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
# Suites that report their cases from one test, not a test per case: the test
# that runs them and, where the suite declares them, its list of cases.
SUITE_TESTS = {
    "DEV": ("test_developer_journey", "CASES"),
    "DJR": ("test_developer_journey_release", "INSTALLS"),
    "PSI-LIVE": ("test_preview_sign_in_live", "CASES"),
    "KDEV": ("test_kind_protected", "CASES"),
    "KEY-09": ("test_native_api_keys_only", None),
}
UNRUN_MARKS = {"live", "optional"}
# pytest.ini's addopts: the marker expression a command with no -m runs.
DEFAULT_MARKS = "not live"
# Files read by the checks below. DCSM-07 replaces some with changed copies.
OVERRIDES = {}


def read(path):
    path = Path(path).resolve()
    return OVERRIDES[path] if path in OVERRIDES else path.read_text()


def prefix_of(case):
    # DU-C1 belongs to DU-C, DU-01 to DU.
    return re.sub(r"-?\d+$", "", case)


def source_of(case):
    if case in CASE_SOURCES:
        return CASE_SOURCES[case]
    assert prefix_of(case) in SOURCES, f"{case} has no known catalog"
    return SOURCES[prefix_of(case)]


def suite_of(case):
    return SUITE_TESTS.get(case) or SUITE_TESTS.get(prefix_of(case))


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


def module_assigns(tree):
    """Module-level assignments, including those under a module-level `if`."""
    nodes = list(tree.body)
    while nodes:
        node = nodes.pop(0)
        if isinstance(node, ast.If):
            nodes[:0] = node.body + node.orelse
        elif isinstance(node, ast.Assign):
            yield node


def assigned(tree, name):
    for node in module_assigns(tree):
        if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
    return None


def is_tested(case, code):
    """A test function named after the case, or the case ID in a string.

    A comment never counts, so a case mentioned only in a comment is untested.
    """
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and re.match(
            case_test_pattern(case), node.name
        ):
            return True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.search(rf"(?<![\w-]){re.escape(case)}(?![\w-])", node.value)
        ):
            return True
    return False


def mark_names(nodes):
    """The names of every `pytest.mark.<name>` in these expressions."""
    found = set()
    for node in nodes:
        for part in ast.walk(node):
            if (
                isinstance(part, ast.Attribute)
                and isinstance(part.value, ast.Attribute)
                and part.value.attr == "mark"
            ):
                found.add(part.attr)
    return found


def case_tests(case, path):
    """The test functions that run the case, each with all its marks."""
    tree = ast.parse(read(path))
    module = assigned(tree, "pytestmark")
    module_marks = mark_names([module]) if module is not None else set()
    suite = suite_of(case)
    tests = {
        node.name: module_marks | mark_names(node.decorator_list)
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and (
            node.name == suite[0]
            if suite
            else re.match(case_test_pattern(case), node.name)
        )
    }
    assert tests, f"{case} has no test that runs it in {path.name}"
    return tests


def selects(expression, marks):
    """Whether pytest's `-m` expression selects a test with these marks."""
    tokens = re.findall(r"\(|\)|[\w-]+", expression)
    assert "".join(tokens) == re.sub(r"\s+", "", expression), expression
    python = " ".join(
        token if token in ("and", "or", "not", "(", ")") else str(token in marks)
        for token in tokens
    )
    return eval(python, {"__builtins__": {}})  # only True, False, and, or, not


def job_section(workflow, job):
    match = re.search(
        rf"^  {re.escape(job)}:\n(.*?)(?=^  [\w-]+:\n|\Z)",
        read(workflow),
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"{workflow.name} has no {job} job"
    return match.group(1)


def without_comments(text):
    """The text with YAML and shell comments removed, line by line."""
    kept = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        quote = None
        for index, character in enumerate(line):
            if quote:
                quote = None if character == quote else quote
            elif character in "\"'":
                quote = character
            elif character == "#" and (index == 0 or line[index - 1].isspace()):
                line = line[:index].rstrip()
                break
        kept.append(line)
    return "\n".join(kept)


def job_env(section):
    """The job's own `env:` values, with folded (`>-`) values joined."""
    match = re.match(r"(?:.*\n)*?    env:\n((?:      .*\n|\s*\n)+)", section)
    env = {}
    if not match:
        return env
    name = None
    for line in match.group(1).splitlines():
        entry = re.match(r"      (\w+):\s*(.*)$", line)
        if entry:
            name, value = entry.groups()
            env[name] = "" if value in (">-", ">", "|") else value
        elif name and line.strip():
            env[name] = (env[name] + " " + line.strip()).strip()
    return env


def job_commands(workflow, job):
    """Each pytest command the job really runs: its -m expression and files.

    Comments are ignored, so a file commented out of the job is not run, and
    `$NAME` takes the job's own env value. A collect-only listing runs nothing.
    """
    section = without_comments(job_section(workflow, job))
    env = job_env(section)
    script = re.sub(r"\\\n\s*", " ", section)
    script = re.sub(r"\$\{?(\w+)\}?", lambda m: env.get(m.group(1), m.group(0)), script)
    commands = []
    for line in script.splitlines():
        if "-m pytest" not in line or "--collect-only" in line:
            continue
        arguments = line.split("-m pytest", 1)[1]
        expression = re.findall(
            r"(?:^|\s)-m\s+(?:\"([^\"]*)\"|'([^']*)'|(\S+))", arguments
        )
        marks = next((m for m in (expression[-1] if expression else ()) if m), None)
        files = re.findall(r"tests/[\w/]+\.py(?:::\w+)?", arguments)
        commands.append((marks or DEFAULT_MARKS, files))
    return section, commands


def runs_in_ci(case):
    _, test_file, job = source_of(case)
    path = TESTS / test_file
    if job is None:
        return False
    if job in ("unit", "integration"):
        shard = shard_of(path)
        # The shards run every unit and integration file with pytest.ini's
        # default selection.
        assert "pytest tests/unit tests/integration --shard" in without_comments(
            job_section(CHECKS, "backend-tests")
        )
        # The shards don't fail on a skip, and live or optional checks need
        # their own job, so a test with either mark never counts here.
        return bool(
            shard
            and shard.startswith(job)
            and all(
                not marks & UNRUN_MARKS for marks in case_tests(case, path).values()
            )
        )
    section, commands = job_commands(JOBS[job], job)
    tests = case_tests(case, path)
    for expression, files in commands:
        for name, marks in tests.items():
            listed = (
                f"tests/{test_file}" in files or f"tests/{test_file}::{name}" in files
            )
            # The job must select the test, and fail when a case is skipped.
            if listed and selects(expression, marks) and "skipped" in section:
                return True
    return False


def declared_cases(case):
    """The cases the suite that runs this case declares, or None."""
    suite = suite_of(case)
    if not suite or not suite[1]:
        return None
    test_file = source_of(case)[1]
    value = assigned(ast.parse(read(TESTS / test_file)), suite[1])
    assert value is not None, f"{test_file} declares no {suite[1]}"
    return set(ast.literal_eval(value))


def test_dcsm_01_every_spec_scenario_is_listed_once():
    assert set(scenario_rows()) == SCENARIOS
    assert NOT_PROVEN <= SCENARIOS


def check_row(scenario, proven_by, closest, not_proven):
    """DCSM-02 for one row of the table."""
    assert closest, f"{scenario} has an empty closest-evidence cell"
    if scenario in not_proven:
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


def test_dcsm_02_proven_scenarios_name_cases_and_unproven_ones_say_why():
    for scenario, (proven_by, closest) in scenario_rows().items():
        check_row(scenario, proven_by, closest, NOT_PROVEN)


# Made-up rows for the not-proven path, which the real table doesn't use today.
SYNTHETIC = ("ST99", "A made-up scenario")
REASON = "Not proven yet: no CI job runs the journey with a real provider yet. DEV-04"


@pytest.mark.parametrize(
    ("proven_by", "closest", "problem"),
    [
        (REASON, "DEV-10 comes close.", None),
        ("DEV-04", "DEV-10 comes close.", "must start with 'Not proven yet:'"),
        ("Not built yet: no CI job runs it. DEV-04", "DEV-10", "must start"),
        ("Not proven yet: DEV-04 is missing.", "DEV-10", "gives no reason"),
        ("Not proven yet: not run. DEV-04", "DEV-10", "gives no reason"),
        (REASON, "", "empty closest-evidence cell"),
        (REASON, "—", "names no closest evidence"),
    ],
)
def test_dcsm_02_a_not_proven_row_says_why_before_naming_cases(
    proven_by, closest, problem
):
    if problem is None:
        check_row(SYNTHETIC, proven_by, closest, {SYNTHETIC})
        return
    with pytest.raises(AssertionError, match=re.escape(problem)):
        check_row(SYNTHETIC, proven_by, closest, {SYNTHETIC})


def test_dcsm_02_a_proven_row_never_says_not_proven():
    with pytest.raises(AssertionError):
        check_row(SYNTHETIC, REASON, "DEV-10", set())
    with pytest.raises(AssertionError, match="names no case"):
        check_row(SYNTHETIC, "the journey", "—", set())


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
        assert is_tested(case, read(TESTS / test_file)), (
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


def test_dcsm_06_suite_cases_are_ones_their_suite_declares():
    # A DEV or PSI-LIVE case counts only once its suite declares it in CASES,
    # whatever other files or comments mention it. The live-gateway job runs
    # each suite and fails when a declared case doesn't pass.
    for case in sorted(named_cases()):
        declared = declared_cases(case)
        if prefix_of(case) in ("DEV", "PSI-LIVE"):
            assert declared is not None, f"{case} has no declared case list"
        if declared is not None:
            assert case in declared, f"{case} isn't in its suite's CASES"


def changed(path, old, new):
    """Read `path` as if `old` were replaced by `new` (DCSM-07)."""
    text = path.read_text()
    assert old in text, f"{old!r} isn't in {path.name}"
    OVERRIDES[path.resolve()] = text.replace(old, new, 1)


ADMIN_TEST = TESTS / "integration/test_cli_admin_sign_in.py"
ADMIN_FILE = "        tests/integration/test_cli_admin_sign_in.py\n"


def test_dcsm_07_a_check_ci_does_not_run_never_counts(monkeypatch):
    monkeypatch.setattr(f"{__name__}.OVERRIDES", {})
    assert runs_in_ci("ADM-INT-01")
    # The test loses its live mark, so the job's -m "optional and live"
    # deselects it.
    changed(ADMIN_TEST, "    pytest.mark.live,\n", "")
    assert not runs_in_ci("ADM-INT-01")
    OVERRIDES.clear()
    # The job's -m no longer selects it.
    changed(CHECKS, '-m "optional and live"', '-m "optional and not live"')
    assert not runs_in_ci("ADM-INT-01")
    OVERRIDES.clear()
    # The file is commented out of the job's command.
    changed(CHECKS, ADMIN_FILE, ADMIN_FILE.replace("tests/", "# tests/"))
    assert not runs_in_ci("ADM-INT-01")
    OVERRIDES.clear()
    # A case mentioned only in a comment is untested.
    assert not is_tested("ADM-INT-02", read(ADMIN_TEST))
    assert "ADM-INT-04" in read(ADMIN_TEST) and not is_tested(
        "ADM-INT-04", read(ADMIN_TEST)
    )
    # A case the suite doesn't declare isn't counted; DEV-10 is its last one.
    assert "DEV-10" in declared_cases("DEV-01")
    assert "DEV-11" not in declared_cases("DEV-01")
    # A live or optional test is never counted as run by the shards.
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
    monkeypatch.setitem(
        SUITE_TESTS,
        "PCLI-04",
        ("test_installed_personal_keys_tools_refresh_resume_logout", None),
    )
    assert not runs_in_ci("PCLI-04")
    # A catalog with no CI job never counts.
    monkeypatch.setitem(
        CASE_SOURCES,
        "NB-02",
        ("unit/cli-no-browser-cases.md", "unit/test_cli_no_browser.py", None),
    )
    assert not runs_in_ci("NB-02")


def test_dcsm_08_marker_expressions_select_as_pytest_does():
    assert selects("optional and live", {"optional", "live", "django_db"})
    assert not selects("optional and live", {"optional"})
    assert selects("not live", set()) and not selects("not live", {"live"})
    assert selects("optional", {"optional"})
    assert selects("(live or optional) and not kubernetes", {"live"})
