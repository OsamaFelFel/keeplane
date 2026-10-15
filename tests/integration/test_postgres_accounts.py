"""Real Keeplane APIs on two app copies and one disposable PostgreSQL database."""

import pytest

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parents[2]
POSTGRES = (
    "postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
)


def run_cases():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wheels",
        type=Path,
        help="Optional offline cache; otherwise download the pinned fixture wheels with hash enforcement",
    )
    parser.add_argument(
        "--app-image",
        help="Test an already packaged PostgreSQL image instead of the disposable binary driver",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Evidence already exists; choose a fresh output")
    if args.app_image and (
        args.wheels or not re.fullmatch(r"[a-zA-Z0-9./:@_-]+", args.app_image)
    ):
        parser.error("Use a valid packaged image reference without --wheels")
    project = "keeplane-postgres-api-" + uuid.uuid4().hex[:10]
    image = project + ":local"
    result = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "postgres_image": POSTGRES,
        "cases": [],
        "completed": False,
        "fixture_removed": False,
        "release_approved": False,
        "limits": [
            "The fixture gateway proves persistence/API coordination, not runtime gateway policy.",
            "This HTTP/internal-network fixture does not prove database TLS, production packaging or backup operations.",
            "The disposable binary driver is not the selected release distribution; native source/notice work remains.",
            "The existing Docker and kind previews are not reset or cut over by this test.",
        ],
    }

    def run(command, input_data=None, check=True):
        item = subprocess.run(
            command, input=input_data, capture_output=True, timeout=420
        )
        if check and item.returncode:
            # Keep enough context to diagnose CI failures, with fixture secrets removed.
            detail = (item.stderr + item.stdout).decode(errors="replace")
            for name in (
                "database",
                "first-admin-password",
                "original-password",
                "rotated",
                "signing",
            ):
                path = root / name
                if path.is_file():
                    detail = detail.replace(path.read_text().strip(), "[redacted]")
            detail = re.sub(r"Bearer [A-Za-z0-9._-]+", "Bearer [redacted]", detail)
            lines = detail.splitlines()
            result["failure_frames"] = [
                line.strip()
                for line in lines
                if re.match(r'\s*File "[^"\n]+", line \d+', line)
            ]
            result["failure_step"] = [
                part.replace(str(root), "<fixture>") for part in command
            ]
            result["failure_output_tail"] = lines[-40:]
            raise RuntimeError(command[0] + " returned " + str(item.returncode))
        return item

    with tempfile.TemporaryDirectory(prefix=project + "-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        for name in ("database", "first-admin-password", "rotated", "signing"):
            path = root / name
            path.write_text(secrets.token_urlsafe(48))
            path.chmod(0o600)
        (root / "original-password").write_text(
            (root / "first-admin-password").read_text()
        )
        (root / "original-password").chmod(0o600)
        state = root / "state"
        state.mkdir(mode=0o700)
        build = root / "build"
        build.mkdir()
        if args.wheels:
            shutil.copytree(args.wheels, build / "wheels")
        else:
            (build / "wheels").mkdir()
        shutil.copyfile(
            ROOT / "tests/fixtures/requirements-postgres-test.txt",
            build / "wheels/trial-requirements.txt",
        )
        shutil.copytree(
            ROOT / "components/control-plane",
            build / "app",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copytree(
            ROOT / "tests",
            build / "tests",
            ignore=shutil.ignore_patterns(
                "__pycache__", "runs", "node_modules", "*-snapshots", "test-results"
            ),
        )
        shutil.copyfile(
            ROOT / "tests/fixtures/postgres_gateway.py", build / "fixture.py"
        )
        (build / "fixture-config.yaml").write_text("fixture: postgres-api\n")
        source = hashlib.sha256()
        for path in sorted((build / "app").rglob("*.py")):
            source.update(
                str(path.relative_to(build / "app")).encode()
                + b"\0"
                + path.read_bytes()
            )
        result["backend_source_sha256"] = source.hexdigest()
        base_image = args.app_image or "keeplane-preview:kind-local"
        result["base_app_image"] = (
            run(["docker", "image", "inspect", base_image, "--format", "{{.Id}}"])
            .stdout.decode()
            .strip()
        )
        if args.app_image:
            result["limits"][2] = (
                "This tests the packaged native driver; complete base-image source/notice work remains."
            )
        (build / "Dockerfile").write_text(
            "FROM "
            + base_image
            + "\nUSER 0\n"
            + (
                ""
                if args.app_image
                else "COPY wheels /wheels/\n"
                "RUN pip install --no-index --find-links /wheels --require-hashes --no-deps --target /deps -r /wheels/trial-requirements.txt\n"
            )
            + "COPY app /app/\nCOPY tests /tests/\nCOPY fixture.py /fixture.py\n"
            "COPY fixture-config.yaml /fixture-config.yaml\nENV PYTHONPATH=/deps:/app:/\n"
        )
        environment = {
            "KEEPLANE_DATABASE_HOST": "database",
            "KEEPLANE_DATABASE_NAME": "keeplane",
            "KEEPLANE_DATABASE_USER": "keeplane",
            "KEEPLANE_DATABASE_PASSWORD_FILE": "/run/secrets/database",
            "KEEPLANE_DATABASE_SSLMODE": "disable",
            "DJANGO_SECRET_KEY_FILE": "/run/secrets/signing",
            "FIRST_ADMIN_PASSWORD_FILE": "/run/secrets/first-admin-password",
            "PUBLIC_ORIGIN": "http://app-a:3000",
            "PUBLIC_ORIGIN_ALIASES": "http://app-b:3000",
            "GATEWAY_URL": "http://gateway:4000",
            "GATEWAY_FILE_CONFIG": "/fixture-config.yaml",
            "KEEPLANE_RUNTIME_DIR": "/run/secrets",
            "KEEPLANE_TEST_IDENTITY": "Django/PostgreSQL API fixture",
            "KEEPLANE_TEST_REPORT_DIR": "/trial-state/reports",
        }
        app = {
            "image": image,
            "user": str(os.getuid()) + ":" + str(os.getgid()),
            "command": [
                "gunicorn",
                "--config",
                "/app/config/gunicorn.conf.py",
                "config.wsgi:application",
            ],
            "environment": environment,
            "secrets": [
                "database",
                "first-admin-password",
                "original-password",
                "rotated",
                "signing",
            ],
            "volumes": [str(state) + ":/trial-state"],
            "healthcheck": {
                "test": [
                    "CMD",
                    "python",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/health/app', timeout=2)",
                ],
                "interval": "1s",
                "timeout": "3s",
                "retries": 40,
            },
        }
        compose = {
            "services": {
                "database": {
                    "image": POSTGRES,
                    "environment": {
                        "POSTGRES_USER": "keeplane",
                        "POSTGRES_DB": "keeplane",
                        "POSTGRES_PASSWORD_FILE": "/run/secrets/database",
                    },
                    "secrets": ["database"],
                    "volumes": ["postgres-data:/var/lib/postgresql/data"],
                    "healthcheck": {
                        "test": [
                            "CMD",
                            "pg_isready",
                            "-U",
                            "keeplane",
                            "-d",
                            "keeplane",
                        ],
                        "interval": "1s",
                        "timeout": "3s",
                        "retries": 40,
                    },
                },
                "gateway": {"image": image, "command": ["python", "/fixture.py"]},
                "app-a": dict(app),
                "app-b": dict(app),
            },
            "volumes": {"postgres-data": {}},
            "networks": {"default": {"internal": True}},
            "secrets": {
                name: {"file": str(root / name)}
                for name in (
                    "database",
                    "first-admin-password",
                    "original-password",
                    "rotated",
                    "signing",
                )
            },
        }
        config = root / "compose.json"
        config.write_text(json.dumps(compose))
        command = ["docker", "compose", "-p", project, "-f", str(config)]

        def dc(*arguments, input_data=None, check=True):
            return run(command + list(arguments), input_data, check)

        def probe(action):
            output = dc(
                "exec",
                "-T",
                "app-a",
                "python",
                "/tests/fixtures/postgres_probe.py",
                action,
            )
            return json.loads(output.stdout)

        def record(identifier, action):
            result["failed_case"] = identifier
            observed = action()
            result["cases"].append(
                {"case": identifier, "verdict": "pass", "observed": observed}
            )
            result.pop("failed_case", None)
            print(identifier + ": PASS", flush=True)

        def existing_suite(script, count):
            output = dc(
                "exec",
                "-T",
                "-e",
                "KEEPLANE_BASE_URL=http://app-a:3000",
                "app-a",
                "python",
                "/tests/e2e/" + script,
            )
            report = (
                json.loads((state / "reports/2026-10-10-users-react.json").read_text())
                if script == "test_accounts.py"
                else json.loads(output.stdout)
            )
            cases = report["cases"]
            assert len(cases) == count and all(
                case["verdict"] == "pass" for case in cases
            )
            return {"cases_passed": count, "cases": cases}

        def ready_database():
            for _ in range(60):
                if (
                    dc(
                        "exec",
                        "-T",
                        "database",
                        "pg_isready",
                        "-U",
                        "keeplane",
                        "-d",
                        "keeplane",
                        check=False,
                    ).returncode
                    == 0
                ):
                    return
                time.sleep(1)
            raise RuntimeError("Fixture database did not recover")

        try:
            if not args.wheels and not args.app_image:
                run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--user",
                        "0",
                        "-v",
                        str(build / "wheels") + ":/wheels",
                        "keeplane-preview:kind-local",
                        "pip",
                        "--isolated",
                        "download",
                        "--no-cache-dir",
                        "--index-url",
                        "https://pypi.org/simple",
                        "--require-hashes",
                        "--no-deps",
                        "--only-binary=:all:",
                        "--dest",
                        "/wheels",
                        "-r",
                        "/wheels/trial-requirements.txt",
                    ]
                )
            run(["docker", "build", "--network=none", "-t", image, str(build)])
            dc("up", "-d", "--wait", "--wait-timeout", "90", "database", "gateway")
            dc(
                "run",
                "--rm",
                "--no-deps",
                "app-a",
                "python",
                "/app/manage.py",
                "migrate",
                "--noinput",
            )
            dc("run", "--rm", "--no-deps", "app-a", "python", "/app/manage.py", "check")
            dc(
                "run",
                "--rm",
                "--no-deps",
                "app-a",
                "python",
                "/app/manage.py",
                "makemigrations",
                "--check",
                "--dry-run",
            )
            dc("up", "-d", "--wait", "--wait-timeout", "90", "app-a", "app-b")
            result["runtime_versions"] = probe("versions")
            record("PGAPI-01", lambda: existing_suite("test_accounts.py", 21))
            record("PGAPI-02", lambda: existing_suite("test_csrf.py", 8))
            record("PGAPI-03", lambda: probe("shared"))
            record("PGAPI-04", lambda: probe("idempotency"))
            record("PGAPI-05", lambda: probe("limits"))
            record("PGAPI-06", lambda: probe("persistence"))
            record("PGAPI-07", lambda: probe("atomic-failure"))
            record("PGAPI-08", lambda: probe("expiry"))
            dc("stop", "database")
            record("PGAPI-09", lambda: probe("outage"))
            dc("start", "database")
            ready_database()
            record("PGAPI-10", lambda: probe("recovery"))
            dc("restart", "app-a", "app-b")
            dc("up", "-d", "--wait", "--wait-timeout", "90", "app-a", "app-b")
            record("PGAPI-11", lambda: probe("recovery"))
            backup = dc(
                "exec",
                "-T",
                "database",
                "pg_dump",
                "-U",
                "keeplane",
                "-d",
                "keeplane",
                "-Fc",
            ).stdout
            dc("exec", "-T", "database", "createdb", "-U", "keeplane", "restored")
            dc(
                "exec",
                "-T",
                "database",
                "pg_restore",
                "-U",
                "keeplane",
                "-d",
                "restored",
                input_data=backup,
            )
            for service in ("app-a", "app-b"):
                compose["services"][service]["environment"] = dict(
                    environment, KEEPLANE_DATABASE_NAME="restored"
                )
            config.write_text(json.dumps(compose))
            dc(
                "up",
                "-d",
                "--force-recreate",
                "--wait",
                "--wait-timeout",
                "90",
                "app-a",
                "app-b",
            )
            record("PGAPI-12", lambda: probe("recovery"))
            probe("prepare-rotation")
            (root / "first-admin-password").write_text((root / "rotated").read_text())
            dc("restart", "app-b")
            dc("up", "-d", "--wait", "--wait-timeout", "90", "app-b")
            record("PGAPI-13", lambda: probe("rotation"))
            record("PGAPI-14", lambda: probe("ascii-usernames"))
            record("PGAPI-15", lambda: probe("class-invariants"))
            result["completed"] = True
        except Exception as error:
            result["fixture_error"] = type(error).__name__ + ": " + str(error)
        finally:
            cleanup = dc("down", "--volumes", "--remove-orphans", check=False)
            remaining = [
                run(
                    [
                        "docker",
                        *arguments,
                        "--filter",
                        "label=com.docker.compose.project=" + project,
                    ]
                ).stdout.strip()
                for arguments in (
                    ["ps", "-aq"],
                    ["volume", "ls", "-q"],
                    ["network", "ls", "-q"],
                )
            ]
            run(["docker", "image", "rm", image], check=False)
            image_absent = (
                run(["docker", "image", "inspect", image], check=False).returncode != 0
            )
            result["fixture_removed"] = (
                cleanup.returncode == 0 and not any(remaining) and image_absent
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output_file:
        json.dump(result, output_file, indent=2)
        output_file.write("\n")
    print(
        json.dumps(
            {
                key: result.get(key)
                for key in ("completed", "fixture_removed", "fixture_error")
            }
        )
    )
    return 0 if result["completed"] and result["fixture_removed"] else 1


if __name__ == "__main__":
    raise SystemExit(run_cases())


def test_postgres_accounts(monkeypatch, report_file, request, capsys):
    arguments = [__file__, "--output", str(report_file)]
    if request.config.getoption("--app-image"):
        arguments += ["--app-image", request.config.getoption("--app-image")]
    monkeypatch.setattr("sys.argv", arguments)
    assert run_cases() in (None, 0)
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    verify_cases(__file__, output.out, report_file)


pytestmark = [pytest.mark.live]
