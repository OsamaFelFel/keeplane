"""Spec 009: the developer half of the MVP journey on the default preview.

Runs DEV-01 to DEV-05 in order (task 009-13) against the Docker preview started
by ``python3 deploy/local/up.py`` with no flags. A temporary developer signs in
from the source-tree CLI through the browser flow, lists and chooses a model in
a sample Git repo with a failing test, and runs ``keeplane code`` with the real
pinned OpenCode 2.0.27 runtime through the guarded gateway. The model is a
deterministic, tool-capable fixture an admin adds and approves as a local
model (``tests/fixtures/journey_coder.py``), so the runtime's read and edit
really happen. Before the task, the developer saves a temperature and a
maximum output for that model in their CLI settings file, and the fixture
checks they arrive unchanged (DEV-03b, Spec 004 ST26). DEV-04 adds the
preview's fixture cloud model on a shared key for the estimated cost. A second developer runs one task, and neither
developer's totals include the other's. Then the developer signs out and
nothing more is sent. Afterwards it removes what it created.

The runtime comes from ``KEEPLANE_OPENCODE_V2_BIN`` (the hash-pinned binary the
``coding-runtime`` check downloads). Without it, DEV-03 and DEV-04 are recorded
as not run and the test is skipped, so CI fails. DEV-03b is also not run until
the CLI has ``request_settings.py`` (task 009-12). See
developer-journey-cases.md.
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import pytest

from components.cli import coding, project_identity, settings_file, usage
from components.cli.keeplane import SWITCHED
from components.cli.sign_in_again import SIGNED_OUT
from tests.e2e import test_preview_sign_in_live as preview
from tests.e2e import test_project_classes_live as classes
from tests.fixtures.journey_coder import ANSWER, USAGE, JourneyCoder
from tests.support.client import BASE, RUNTIME, Browser
from tests.support.gateway import GATEWAY_SCRIPT, RESOURCE_PATH
from tests.support.reporting import report_path

pytestmark = [pytest.mark.live, pytest.mark.docker_only]

REPORT = report_path("developer-journey.json")
CASES = ("DEV-01", "DEV-02", "DEV-03", "DEV-03b", "DEV-04", "DEV-05")
# Spec 004 ST26: what the developer saves for the model reaches it unchanged.
REQUEST_SETTINGS = {"temperature": 0.37, "max_tokens": 777}
# The binary the ADR 007 trials recorded and the coding-runtime check pins.
RUNTIME_SHA256 = "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"
# A priced row in the shipped list, served by the preview's cloud fixture.
CLOUD_UPSTREAM = "gpt-5-mini"
FAILING = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TEST_FILE = (
    "import unittest\n\nfrom calc import add\n\n\n"
    "class AddTest(unittest.TestCase):\n"
    "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n\n"
    'if __name__ == "__main__":\n    unittest.main()\n'
)
TASK = "Make the failing test pass"


def runtime_binary():
    """The pinned runtime, or None when this machine doesn't have it."""
    given = os.environ.get("KEEPLANE_OPENCODE_V2_BIN")
    if not given or not Path(given).is_file():
        return None
    if hashlib.sha256(Path(given).read_bytes()).hexdigest() != RUNTIME_SHA256:
        raise RuntimeError("KEEPLANE_OPENCODE_V2_BIN is not the pinned 2.0.27 binary")
    return Path(given)


def sample_repo(directory, remote):
    """A new Git repo with one small Python file and its failing test."""
    directory.mkdir()
    git = ["git", "-C", str(directory), "-c", "init.defaultBranch=main"]
    identity = ["-c", "user.name=Journey", "-c", "user.email=journey@example.test"]
    subprocess.run([*git, "init", "-q"], check=True, timeout=30)
    subprocess.run([*git, "remote", "add", "origin", remote], check=True, timeout=30)
    (directory / "calc.py").write_text(FAILING)
    (directory / "test_calc.py").write_text(TEST_FILE)
    subprocess.run([*git, "add", "."], check=True, timeout=30)
    subprocess.run(
        [*git, *identity, "commit", "-q", "-m", "Sample"], check=True, timeout=30
    )
    return directory


def sample_tests_pass(directory):
    result = subprocess.run(
        [sys.executable, "test_calc.py"],
        cwd=directory,
        capture_output=True,
        timeout=60,
        check=False,
    )
    return result.returncode == 0


def changed_files(directory):
    result = subprocess.run(
        ["git", "-C", str(directory), "diff", "--name-only"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.split()


class Developer(preview.Cli):
    """A developer at their own machine: own home folder, CLI and runtime on PATH."""

    def __init__(self, home, username, password, runtime):
        home.mkdir()
        super().__init__(home, username, password)
        if runtime is not None:
            tools = home / "bin"
            tools.mkdir()
            (tools / "opencode").symlink_to(runtime)
            self.env["PATH"] = str(tools) + os.pathsep + self.env.get("PATH", "")

    def run(self, *arguments, cwd=None, timeout=300):
        result = subprocess.run(
            [sys.executable, str(preview.CLI), *arguments],
            env=self.env,
            cwd=cwd or self.home,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def profile(self):
        return self.home / ".config/keeplane/account"

    def token(self):
        return preview.access_token(self.profile())


def usage_rows(token):
    data, _ = usage.fetch(BASE, token, None)
    return data, {row["model"]: row for row in data["models"]}


def counts(row, period):
    return {name: row[period][name] for name in usage.COUNTS} if row else None


def project_entry(admin, name):
    status, listing, _ = admin.fetch("/api/projects?" + urlencode({"search": name}))
    if status != 200:
        return None
    return next((row for row in listing["projects"] if row["name"] == name), None)


def run_cases():
    binary = runtime_binary()
    suffix = uuid.uuid4().hex[:8]
    coder_model, coder_upstream = "journey-coder-" + suffix, "journey-up-" + suffix
    cloud_model = "journey-cloud-" + suffix
    remote = f"https://git.example.test/journey/sample-{suffix}.git"
    project_name = f"journey/sample-{suffix}"
    project_id = project_identity.remote_project(remote).id
    password = (RUNTIME / "first-admin-password").read_text().strip()
    cloud_key = (RUNTIME / "cloud-provider-key").read_text().strip()
    names = {"first": "journey-dev-" + suffix, "second": "journey-second-" + suffix}
    secrets = {key: uuid.uuid4().hex + uuid.uuid4().hex for key in names}
    cases, failures = [], []
    state = {"users": [], "models": []}
    approved_before = []
    admin = Browser()

    def record(identifier, verdict, observed):
        cases.append({"id": identifier, "verdict": verdict, "observed": observed})

    def not_run(identifier):
        record(
            identifier,
            "not-run",
            {"reason": "KEEPLANE_OPENCODE_V2_BIN does not name the pinned runtime"},
        )

    with (
        tempfile.TemporaryDirectory(prefix="keeplane-journey-") as directory,
        JourneyCoder([coder_upstream], port=classes.RUNNER_PORT) as coder,
    ):
        root = Path(directory)
        first = Developer(root / "first", names["first"], secrets["first"], binary)
        second = Developer(root / "second", names["second"], secrets["second"], binary)
        repo = sample_repo(root / "first/sample", remote)
        clone = sample_repo(root / "second/sample", remote)
        try:
            assert admin.login("first-admin", password)[0] == 200
            _, listing, _ = admin.fetch("/api/models")
            approved_before = sorted(
                row["id"] for row in listing["models"] if row.get("approved")
            )
            if not preview.wait_for_report(
                preview.settled(len(approved_before)), timeout=300
            ):
                raise RuntimeError("The model enroller did not settle before the cases")
            for key in ("first", "second"):
                status, user, _ = admin.fetch(
                    "/api/users",
                    {
                        "username": names[key],
                        "role": "developer",
                        "password": secrets[key],
                    },
                    method="POST",
                )
                if status != 201:
                    raise RuntimeError(f"Creating a developer returned {status}")
                state["users"].append(user["id"])
            # The admin adds and approves the two models, as in Models and routing.
            for payload in (
                {
                    "name": coder_model,
                    "model": coder_upstream,
                    "source": "runner",
                    "address": classes.RUNNER_ADDRESS,
                    "approved_classes": ["Public"],
                },
                {
                    "name": cloud_model,
                    "model": CLOUD_UPSTREAM,
                    "source": "openai",
                    "key_choice": "shared",
                    "shared_key": cloud_key,
                    "approved_classes": ["Public"],
                },
            ):
                status, result, _ = admin.fetch("/api/models", payload, method="POST")
                if status != 200:
                    raise RuntimeError(
                        f"Adding {payload['name']} returned {status}: {result}"
                    )
                state["models"].append(payload["name"])
            if not preview.wait_for_report(
                preview.settled(len(approved_before) + 2), timeout=120
            ):
                raise RuntimeError("The model enroller did not enroll the two models")
            _, listing, _ = admin.fetch("/api/models")
            approved = {row["id"] for row in listing["models"] if row.get("approved")}
            unapproved = {
                row["id"] for row in listing["models"] if not row.get("approved")
            }

            # DEV-01: browser sign-in with the CLI's defaults, then whoami.
            code, out, err = first.run("login", "--server", BASE, "--timeout", "60")
            who = first.run("whoami")
            record(
                "DEV-01",
                "pass"
                if code == 0
                and out.endswith("Signed in to Keeplane.")
                and who[0] == 0
                and names["first"] in who[1]
                else "fail",
                {
                    "login_exit": code,
                    "login_output": out.splitlines()[-1:],
                    "login_errors": bool(err),
                    "whoami_exit": who[0],
                    "whoami_output": who[1],
                },
            )

            # DEV-02: in the sample repo, list the models and choose the coder.
            listed = first.run("models", cwd=repo)
            try:
                catalog = json.loads(listed[1])
                shown = {row["id"] for row in catalog["models"]}
            except (ValueError, KeyError, TypeError):
                catalog, shown = None, set()
            chosen = first.run("use", coder_model, cwd=repo)
            record(
                "DEV-02",
                "pass"
                if listed[0] == 0
                and catalog["project_id"] == project_id
                and {coder_model, cloud_model} <= shown
                and shown <= approved
                and not shown & unapproved
                and chosen[0] == 0
                and chosen[1] == SWITCHED.format(model=coder_model)
                else "fail",
                {
                    "models_exit": listed[0],
                    "listed": sorted(shown),
                    "all_listed_approved": shown <= approved,
                    "unapproved_listed": sorted(shown & unapproved),
                    "unapproved_in_admin_list": len(unapproved),
                    "project_matches_repo": bool(catalog)
                    and catalog.get("project_id") == project_id,
                    "use_exit": chosen[0],
                    "use_output": chosen[1],
                },
            )

            # DEV-03: one coding task with the real runtime through the gateway.
            first_turns = []
            # DEV-03b: the developer's request settings for the model, in the
            # "models" section of their own settings file, before the task.
            with patch.dict(
                os.environ,
                {
                    "HOME": str(first.home),
                    "XDG_CONFIG_HOME": str(first.home / ".config"),
                },
            ):
                settings_file.set_request_settings(coder_model, REQUEST_SETTINGS)
                saved = settings_file.request_settings(coder_model)
            if binary is None:
                not_run("DEV-03")
            else:
                failing_before = not sample_tests_pass(repo)
                coder.target = repo / "calc.py"
                before = coder.served()
                received_before = len(coder.received)
                code, out, err = first.run("code", TASK, cwd=repo)
                answers = coder.served() - before
                received = coder.received[received_before:]
                first_turns.append(answers)
                entry = project_entry(admin, project_name)
                users = [row["username"] for row in (entry or {}).get("users", [])]
                record(
                    "DEV-03",
                    "pass"
                    if failing_before
                    and code == 0
                    and answers >= 3
                    and coder.tools == ["read", "edit"]
                    and (repo / "calc.py").read_text() == FIXED
                    and changed_files(repo) == ["calc.py"]
                    and sample_tests_pass(repo)
                    and ANSWER in out
                    and '"edit"' in out
                    and "calc.py" in out
                    and coding.USING_SWITCH.format(model=coder_model) in err
                    and coding.ANSWERED_BY.format(models=coder_model) in err
                    and entry is not None
                    and entry["id"] == project_id
                    and entry["initialized"] is False
                    and users == [names["first"]]
                    else "fail",
                    {
                        "test_failed_before": failing_before,
                        "code_exit": code,
                        "model_answers": answers,
                        "tool_calls": list(coder.tools),
                        "changed_files": changed_files(repo),
                        "test_passes_after": sample_tests_pass(repo),
                        "answer_shown": ANSWER in out,
                        "edit_shown": '"edit"' in out and "calc.py" in out,
                        "cli_messages": err.splitlines(),
                        "project": entry,
                        "runtime_errors": out.splitlines()[-3:] if code else [],
                    },
                )

            if binary is None:
                not_run("DEV-03b")
            elif importlib.util.find_spec("components.cli.request_settings") is None:
                # Task 009-12 (keeplane #257) gives the settings to the runtime.
                record(
                    "DEV-03b",
                    "not-run",
                    {
                        "reason": "needs components/cli/request_settings.py (task 009-12)"
                    },
                )
            else:
                sent = [
                    {name: row[name] for name in REQUEST_SETTINGS} for row in received
                ]
                record(
                    "DEV-03b",
                    "pass"
                    if saved == REQUEST_SETTINGS
                    and code == 0
                    and len(received) == answers >= 3
                    and all(row == REQUEST_SETTINGS for row in sent)
                    else "fail",
                    {
                        "saved": saved,
                        "code_exit": code,
                        "model_requests": len(received),
                        "received": received,
                    },
                )

            # DEV-04: a second developer works first; then the first developer
            # uses the cloud model and reads their own usage.
            if binary is None:
                not_run("DEV-04")
            else:
                code, _, _ = second.run("login", "--server", BASE, "--timeout", "60")
                if code:
                    raise RuntimeError("The second developer could not sign in")
                coder.target = clone / "calc.py"
                before = coder.served()
                second_task = second.run(
                    "code", "--model", coder_model, TASK, cwd=clone
                )
                second_answers = coder.served() - before
                cloud_task = first.run(
                    "code", "--model", cloud_model, "Say hello", cwd=repo
                )
                shown = first.run("usage", cwd=repo)
                data, mine = usage_rows(first.token())
                _, theirs = usage_rows(second.token())

                def tokens(answers, per):
                    return {
                        "input_tokens": per[0] * answers,
                        "output_tokens": per[1] * answers,
                        "requests": answers,
                        "requests_without_usage": 0,
                    }

                own_coder = tokens(
                    sum(first_turns),
                    (USAGE["prompt_tokens"], USAGE["completion_tokens"]),
                )
                cloud_row = mine.get(cloud_model)
                cloud_requests = (counts(cloud_row, "today") or {}).get("requests", 0)
                own_cloud = tokens(cloud_requests, (2, 3))
                periods = ("today", "this_month")
                lines = shown[1].splitlines()
                label = usage.ESTIMATE_LABEL.format(
                    date=usage.long_date(data["price_list"]["date"])
                    if data["price_list"]
                    else ""
                )

                def table_rows(model):
                    rows = [line.split() for line in lines]
                    start = next(
                        (
                            i
                            for i, row in enumerate(rows)
                            if row[:2] == [model, "Today"]
                        ),
                        None,
                    )
                    return [] if start is None else rows[start : start + 2]

                coder_lines, cloud_lines = (
                    table_rows(coder_model),
                    table_rows(cloud_model),
                )
                record(
                    "DEV-04",
                    "pass"
                    if second_task[0] == 0
                    and second_answers >= 3
                    and (clone / "calc.py").read_text() == FIXED
                    and cloud_task[0] == 0
                    and "mock cloud answer" in cloud_task[1]
                    and coding.ANSWERED_BY.format(models=cloud_model) in cloud_task[2]
                    and set(mine) == {coder_model, cloud_model}
                    and all(counts(mine[coder_model], p) == own_coder for p in periods)
                    and cloud_requests >= 1
                    and all(counts(cloud_row, p) == own_cloud for p in periods)
                    and mine[coder_model]["cost_status"] == "local"
                    and cloud_row["cost_status"] == "estimate"
                    # Tokens counted in the hour the model was added are left
                    # out of the estimate (ADR 029), and the CLI says so.
                    and all(
                        Decimal(cloud_row[p]["estimated_cost"]) > 0
                        or cloud_row[p]["cost_partial"]
                        for p in periods
                    )
                    and (
                        not any(cloud_row[p]["cost_partial"] for p in periods)
                        or usage.PARTIAL_COST.format(model=cloud_model) in shown[1]
                    )
                    and counts(theirs.get(coder_model), "today")
                    == tokens(
                        second_answers,
                        (USAGE["prompt_tokens"], USAGE["completion_tokens"]),
                    )
                    and cloud_model not in theirs
                    and shown[0] == 0
                    and len(coder_lines) == 2
                    and all(row[-1] == usage.LOCAL_COST for row in coder_lines)
                    and coder_lines[0][2:4]
                    == [
                        format(own_coder["input_tokens"], ","),
                        format(own_coder["output_tokens"], ","),
                    ]
                    and len(cloud_lines) == 2
                    and all(row[-1].startswith("$") for row in cloud_lines)
                    and label in shown[1]
                    else "fail",
                    {
                        "second_task_exit": second_task[0],
                        "second_answers": second_answers,
                        "second_usage_today": counts(theirs.get(coder_model), "today"),
                        "cloud_task_exit": cloud_task[0],
                        "cloud_messages": cloud_task[2].splitlines(),
                        "first_answers": first_turns,
                        "expected_coder": own_coder,
                        "coder_usage": {
                            p: counts(mine.get(coder_model), p) for p in periods
                        },
                        "cloud_usage": {p: counts(cloud_row, p) for p in periods},
                        "cost_status": {
                            model: row["cost_status"] for model, row in mine.items()
                        },
                        "cloud_cost": {
                            p: (cloud_row or {}).get(p, {}).get("estimated_cost")
                            for p in periods
                        },
                        "cloud_cost_partial": {
                            p: (cloud_row or {}).get(p, {}).get("cost_partial")
                            for p in periods
                        },
                        "usage_exit": shown[0],
                        "usage_output": lines,
                    },
                )

            # DEV-05: sign out, then try to code: nothing reaches the gateway.
            token = first.token()
            out = first.run("logout")
            before = coder.served()
            attempt = first.run("code", "anything", cwd=repo)
            replay = preview.guarded(token, project_id, coder_model)
            record(
                "DEV-05",
                "pass"
                if out[0] == 0
                and attempt[0] == 1
                and attempt[2] == SIGNED_OUT
                and coder.served() == before
                and replay[0] in (401, 403)
                else "fail",
                {
                    "logout_exit": out[0],
                    "logout_output": out[1],
                    "code_exit": attempt[0],
                    "code_message": attempt[2],
                    "model_answers_after": coder.served() - before,
                    "old_token_at_gateway": replay[0],
                },
            )
        finally:
            for developer in (first, second):
                signed_in = (developer.profile() / "credential.json").exists()
                if signed_in and developer.run("logout")[0]:
                    failures.append(f"{developer.username} logout failed")
            restore(password, state, failures)
            if state["models"] and not preview.wait_for_report(
                preview.settled(len(approved_before)), timeout=300
            ):
                failures.append("the model enroller did not settle after clean-up")
    cleanup = "complete" if not failures else "; ".join(failures)
    report = {
        "suite": "Spec 009 developer journey DEV-01 to DEV-05 on the default preview",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": "OpenCode 2.0.27 (pinned)" if binary else None,
        "cases": cases,
        "cleanup": cleanup,
        "passed": sum(case["verdict"] == "pass" for case in cases),
        "failed": sum(case["verdict"] == "fail" for case in cases),
        "not_run": [case["id"] for case in cases if case["verdict"] == "not-run"],
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"{report['passed']} passed, {report['failed']} failed; cleanup {cleanup}; {REPORT}"
    )
    for case in cases:
        print(case["id"], case["verdict"], json.dumps(case["observed"]))
    return report


def restore(password, state, failures):
    try:
        admin = Browser()
        if admin.login("first-admin", password)[0] != 200:
            raise RuntimeError("sign-in failed")
        for model in state["models"]:
            status, _, _ = admin.fetch(
                f"/api/models/{model}/setup", {}, method="DELETE"
            )
            if status not in (200, 404):
                failures.append(f"{model} setup removal returned {status}")
            removed = classes.compose(
                "exec",
                "-T",
                "app",
                "python",
                "-c",
                GATEWAY_SCRIPT,
                "DELETE",
                RESOURCE_PATH + "/" + model,
                "-",
                timeout=60,
            )
            if removed.returncode:
                failures.append(f"{model} gateway removal could not be confirmed")
        for user in state["users"]:
            status, _, _ = admin.fetch(f"/api/users/{user}", {}, method="DELETE")
            if status != 200:
                failures.append(f"developer removal returned {status}")
        admin.fetch("/sign-out", method="POST")
    except Exception as error:  # noqa: BLE001 - report, never hide, an incomplete restore.
        failures.append(f"restore raised {type(error).__name__}")


def test_developer_journey():
    reason = preview.unavailable_reason()
    if reason:
        pytest.skip(reason)
    report = run_cases()
    assert [case["id"] for case in report["cases"]] == list(CASES)
    assert report["failed"] == 0 and report["cleanup"] == "complete"
    if report["not_run"]:
        pytest.skip("Not run: " + ", ".join(report["not_run"]))


if __name__ == "__main__":
    reason = preview.unavailable_reason()
    if reason:
        print("Not run: " + reason)
        sys.exit(2)
    result = run_cases()
    sys.exit(int(bool(result["failed"]) or result["cleanup"] != "complete"))
