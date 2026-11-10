"""Every Spec 002 scenario is mapped to cases that exist and are tested.

The map is the "Spec 002 scenarios" table in tests/e2e/self-hosting-cases.md.
The plain-English cases are in self-hosting-scenario-map-cases.md.
"""

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
MAP = TESTS / "e2e/self-hosting-cases.md"
# The CI workflow that installs the chart on kind clusters and runs live test
# files on every revision. Each of its jobs (the cluster with outside access
# and the isolated network) has a LIVE_TESTS line naming its files.
LIVE_WORKFLOW = TESTS.parent / ".github/workflows/kubernetes-live.yml"
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
# Scenarios not proven yet. Only a check that CI runs on the current
# revision proves a scenario; a live trial recorded on an earlier chart
# revision is closest evidence. ST4 and ST5 are proven by the K8S cases the
# Kubernetes live workflow runs on kind, ST1 and ST2's registry scenario by
# the ISO cases its isolated-network job runs. The reason lives in the table only: its cell
# starts "Not proven yet:" and says which run is missing before naming cases.
NOT_PROVEN = {
    ("ST2", "Runs where only the models are reachable"),
    ("ST3", "A local model works like a cloud one"),
}
# Catalogs whose cases only render the chart. They can support a scenario but
# never prove one alone.
RENDER_ONLY = {"SHAPE", "NETPOL", "PKG"}
# Catalogs whose checks need a cluster, Docker fixtures or the pinned gateway
# image. They can support a scenario but never prove one alone, except the
# cases of a test file the Kubernetes live workflow runs (live_ci_cases).
NOT_IN_CI = {"K8S", "ISO", "FULL", "EXEDGE", "EXIST", "GW-KEY"}
# Owner decision on governance issue #47: the managed gateway refuses to
# install without the installer's key Secret. Helm evaluates the templates
# before anything reaches the cluster, so a refusal under `helm template` in
# CI is the same refusal `helm install` gives; for this scenario only, these
# refusal cases count as CI proof.
REFUSAL_PROOF = {
    ("ST3", "The managed gateway always requires keys"): {"SHAPE-08", "PKG-04"},
}
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
    "ISO": "e2e/kubernetes-isolated-cases.md",
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


def live_ci_cases():
    """Cases of every test file the Kubernetes live workflow's jobs run.

    Each job fails unless each file runs without a skip and reports exactly
    its declared cases, all passing (tests/support/cases.py).
    """
    from tests.support.cases import EXPECTED_CASES

    lines = re.findall(r"^\s*LIVE_TESTS:\s*(.+)$", LIVE_WORKFLOW.read_text(), re.MULTILINE)
    assert len(lines) == 2, "Each Kubernetes live job names its LIVE_TESTS"
    files = []
    for line in lines:
        assert line.split(), line
        files += line.split()
    for name in files:
        assert re.fullmatch(r"tests/e2e/test_\w+\.py", name), name
        assert (TESTS.parent / name).is_file(), f"{name} does not exist"
    return {case for name in files for case in EXPECTED_CASES[Path(name).stem].split()}


def test_shm_01_every_spec_scenario_is_listed_once():
    assert set(scenario_rows()) == SCENARIOS
    assert set(NOT_PROVEN) <= SCENARIOS


def test_shm_02_proven_scenarios_name_cases_and_unproven_ones_say_why():
    for scenario, checked_by in scenario_rows().items():
        named = CASE.findall(checked_by)
        if scenario in NOT_PROVEN:
            reason = re.match(r"Not proven yet: (.*)", checked_by)
            assert reason, f"{scenario} must start with 'Not proven yet:'"
            # The reason comes before the first case it names, in words.
            before_cases = CASE.split(reason.group(1), 1)[0]
            assert len(re.findall(r"[a-z]+", before_cases)) >= 5, (
                f"{scenario} gives no reason before naming cases"
            )
            # It names the cases that come closest, so the gap is visible.
            assert named, f"{scenario} names no case"
        else:
            assert not checked_by.startswith("Not "), scenario
            assert named, scenario


def test_shm_03_a_proven_scenario_rests_on_a_check_ci_runs():
    for scenario, checked_by in scenario_rows().items():
        if scenario in NOT_PROVEN:
            continue
        named = set(CASE.findall(checked_by))
        in_ci = {
            case
            for case in named
            if prefix_of(case) not in RENDER_ONLY | NOT_IN_CI
        } | (named & live_ci_cases())
        refusals = named & REFUSAL_PROOF.get(scenario, set())
        assert in_ci or refusals, (
            f"{scenario} is proven only by rendering or by checks CI does not run"
        )


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


def test_shm_06_only_the_live_workflow_s_test_files_lift_live_cases():
    cases = live_ci_cases()
    # The replica, customer-run gateway, preflight and gateway-down cases,
    # and the copy-stop cases (a stream cut short, access changes).
    assert {f"K8S-{n:02d}" for n in range(1, 14)} | {
        f"K8S-{n:02d}" for n in range(17, 22)
    } <= cases
    # The simulated preflight retries (K8S-14 to K8S-16) are in another test
    # file this workflow does not run, so they never count through it.
    assert not {"K8S-14", "K8S-15", "K8S-16"} & cases
    # The isolated-network cases, from the workflow's isolated-network job.
    assert {f"ISO-{n:02d}" for n in range(1, 10)} <= cases


# Each clause of a proven scenario whose proof is a separate case: the
# scenario, the clause in Spec 002's words and the cases that prove it.
CLAUSE_PROOF = {
    ("ST4", "One gateway copy stops"): {
        "new model calls are still answered": {"K8S-03"},
        "a reply already streaming from that copy may fail visibly and can be "
        "retried": {"K8S-18"},
    },
}


def test_shm_07_each_clause_with_its_own_proof_names_it_and_ci_runs_it():
    rows = scenario_rows()
    live = live_ci_cases()
    for scenario, clauses in CLAUSE_PROOF.items():
        named = set(CASE.findall(rows[scenario]))
        for clause, cases in clauses.items():
            assert cases <= named, f"{scenario} does not name {cases} for {clause!r}"
            assert cases <= live, f"CI does not run {cases} for {clause!r}"
        assert "not exercised" not in rows[scenario].lower(), scenario
