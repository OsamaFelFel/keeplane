"""Run pytest, browser and deployment groups; retain reports even after failures."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_group(name, command, directory, environment):
    folder = directory / name
    folder.mkdir()
    env = {
        **os.environ,
        **environment,
        "KEEPLANE_TEST_REPORT_DIR": str(folder / "cases"),
    }
    started = time.monotonic()
    stdout = folder / "stdout.txt"
    stderr = folder / "stderr.txt"
    with stdout.open("w") as out, stderr.open("w") as err:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err)
        try:
            code = process.wait(timeout=7200)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    result = {
        "name": name,
        "command": command,
        "exit_code": code,
        "passed": code == 0,
        "seconds": round(time.monotonic() - started, 1),
    }
    junit = folder / "junit.xml"
    if junit.is_file():
        suites = ET.parse(junit).getroot().iter("testsuite")
        result["counts"] = {
            key: 0 for key in ("tests", "failures", "errors", "skipped")
        }
        for suite in suites:
            for key in result["counts"]:
                result["counts"][key] += int(suite.get(key, 0))
    print(name + ": " + ("PASS" if result["passed"] else "FAIL"), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="A new JSON result file"
    )
    parser.add_argument(
        "--group",
        action="append",
        choices=[
            "fast",
            "components",
            "docker",
            "kind",
            "deployments",
            "browser-docker",
            "browser-kind",
        ],
    )
    parser.add_argument("--app-image", default="keeplane-preview:postgres-local")
    args = parser.parse_args()
    output = args.output.resolve()
    directory = output.with_suffix("")
    if output.exists() or directory.exists():
        parser.error("Choose a new output path; previous results are retained")
    directory.mkdir(parents=True)
    selected = args.group or [
        "fast",
        "components",
        "docker",
        "kind",
        "deployments",
        "browser-docker",
        "browser-kind",
    ]
    result = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "completed": False,
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "working_tree_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True
            )
        ),
        "selected_groups": selected,
        "groups": [],
    }
    previews = []

    def pytest_group(name, paths, expression, env=None, extra=None):
        return (
            [
                sys.executable,
                "-m",
                "pytest",
                *paths,
                "-m",
                expression,
                "--junitxml=" + str(directory / name / "junit.xml"),
                *(extra or []),
            ],
            env or {},
        )

    commands = {
        "fast": pytest_group("fast", ["tests/unit", "tests/integration"], "not live"),
        "components": pytest_group(
            "components",
            ["tests/integration"],
            "live",
            extra=["--app-image", args.app_image],
        ),
        "docker": pytest_group(
            "docker",
            ["tests/e2e"],
            "not kubernetes and not infrastructure and not optional",
            {"KEEPLANE_BASE_URL": "http://127.0.0.1:3000"},
        ),
        "kind": pytest_group(
            "kind",
            ["tests/e2e"],
            "not kubernetes and not infrastructure and not optional and not docker_only",
            {"KEEPLANE_BASE_URL": "http://127.0.0.1:13000"},
        ),
        "deployments": pytest_group(
            "deployments",
            ["tests/e2e"],
            "kubernetes or infrastructure",
            {"KEEPLANE_BASE_URL": "http://127.0.0.1:3000"},
        ),
    }
    for name, base in [
        ("browser-docker", "http://127.0.0.1:3000"),
        ("browser-kind", "http://127.0.0.1:13000"),
    ]:
        commands[name] = (
            [
                "npm",
                "--prefix",
                "tests/browser",
                "test",
                "--",
                "--workers=1",
                "--reporter=list,json",
            ],
            {
                "KEEPLANE_BASE_URL": base,
                "PLAYWRIGHT_JSON_OUTPUT_FILE": str(directory / name / "browser.json"),
            },
        )
    try:
        from tests.support.client import Browser, RUNTIME

        bases = set()
        if any(name in selected for name in ["docker", "components", "deployments"]):
            bases.add("http://127.0.0.1:3000")
        if any(name in selected for name in ["kind", "deployments"]):
            bases.add("http://127.0.0.1:13000")
        for base in sorted(bases):
            browser = Browser(base)
            assert (
                browser.login(
                    "first-admin",
                    (RUNTIME / "first-admin-password").read_text().strip(),
                )[0]
                == 200
            )
            status, state, _ = browser.fetch("/api/data-classes")
            if status != 200:
                raise RuntimeError("Could not read data-class mode at " + base)
            previews.append((browser, state["enabled"]))
            if (
                browser.fetch(
                    "/api/data-classes/mode", {"enabled": True}, method="PUT"
                )[0]
                != 200
            ):
                raise RuntimeError("Could not prepare data-class checks at " + base)
        for name in selected:
            command, env = commands[name]
            result["groups"].append(run_group(name, command, directory, env))
            output.write_text(json.dumps(result, indent=2) + "\n")
        result["completed"] = True
    finally:
        result["data_classes_restored"] = []
        for browser, enabled in previews:
            try:
                browser.login(
                    "first-admin",
                    (RUNTIME / "first-admin-password").read_text().strip(),
                )
                status, _, _ = browser.fetch(
                    "/api/data-classes/mode", {"enabled": enabled}, method="PUT"
                )
                result["data_classes_restored"].append(status == 200)
                browser.fetch("/sign-out", method="POST")
            except Exception:
                result["data_classes_restored"].append(False)
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        output.write_text(json.dumps(result, indent=2) + "\n")
    return int(
        not result["completed"]
        or not all(item["passed"] for item in result["groups"])
        or not all(result["data_classes_restored"])
    )


if __name__ == "__main__":
    raise SystemExit(main())
