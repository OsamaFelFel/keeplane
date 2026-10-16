"""Exercise the opt-in sign-in image against an owned PostgreSQL container."""

import json
import os
import secrets
import subprocess
import time
import uuid
from pathlib import Path

import pytest

POSTGRES = "postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
pytestmark = [pytest.mark.live, pytest.mark.infrastructure, pytest.mark.optional]


def test_cli_postgres_image(tmp_path):
    image = os.environ.get("KEEPLANE_CLI_POSTGRES_IMAGE")
    if not image:
        pytest.skip("Set KEEPLANE_CLI_POSTGRES_IMAGE to the combined trial image")
    prefix = "keeplane-cli-image-" + uuid.uuid4().hex[:10]
    database, client = prefix + "-db", prefix + "-app"
    seed = {"password": secrets.token_urlsafe(48), "signing": secrets.token_urlsafe(48)}
    tmp_path.chmod(0o700)
    password = tmp_path / "password"
    password.write_text(seed["password"])
    password.chmod(0o600)

    def run(*arguments, input_data=None, check=True, timeout=120):
        result = subprocess.run(
            ["docker", *arguments], input=input_data, capture_output=True,
            text=True, timeout=timeout, check=False,
        )
        if check:
            detail = result.stdout + result.stderr
            for value in seed.values():
                detail = detail.replace(value, "[redacted]")
            assert result.returncode == 0, detail
        return result

    # Resolve the supplied image once; never pull or mutate an existing tag.
    image_id = run("image", "inspect", image, "--format", "{{.Id}}").stdout.strip()
    probe = Path(__file__).resolve().parents[1] / "fixtures/cli_postgres_image_probe.py"
    created = False
    try:
        run("network", "create", "--internal", prefix)
        created = True
        run(
            "run", "--detach", "--pull", "never", "--name", database,
            "--network", prefix, "--network-alias", "database",
            "--mount", f"type=bind,src={password},dst=/run/database-password,readonly",
            "-e", "POSTGRES_PASSWORD_FILE=/run/database-password",
            "-e", "POSTGRES_USER=keeplane", "-e", "POSTGRES_DB=keeplane", POSTGRES,
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if run("exec", database, "pg_isready", "-h", "127.0.0.1", "-U", "keeplane",
                   "-d", "keeplane", check=False, timeout=5).returncode == 0:
                break
            time.sleep(0.1)
        else:
            pytest.fail("The disposable database did not become ready")
        result = run(
            "run", "--rm", "--interactive", "--pull", "never", "--name", client,
            "--network", prefix, "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", "65532:65532",
            "--tmpfs", "/state:uid=65532,gid=65532,mode=0700",
            "--tmpfs", "/tmp:uid=65532,gid=65532,mode=0700",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "--mount", f"type=bind,src={probe},dst=/probe.py,readonly",
            "--entrypoint", "python", image_id, "/probe.py",
            input_data=json.dumps(seed), timeout=180,
        )
        observed = json.loads(result.stdout.splitlines()[-1])
        assert observed == {
            "uid": 65532, "postgres_impl": "c", "toolkit": "3.4.1",
            "clients": ["keeplane-cli", "keeplane-cli-device"],
            "ready": True, "installers_absent": True,
        }
    finally:
        for name in (client, database):
            run("rm", "--force", "--volumes", name, check=False, timeout=30)
        if created:
            run("network", "rm", prefix, timeout=30)
