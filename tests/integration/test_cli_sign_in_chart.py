"""Opt-in Helm sign-in uses the existing PostgreSQL and HTTPS installation."""

import pytest

from tests.integration.test_chart_package import CHART, named, run

IMAGE = "registry.example.test/keeplane@sha256:" + "a" * 64
BASE = ("-f", "deploy/postgres/values.example.yaml", "--set", "app.image=" + IMAGE)


def render(*extra):
    return run("template", "cli", CHART, *BASE, *extra)


def resources(result):
    assert result.returncode == 0, result.stderr
    return (
        named(result.stdout, "Deployment", "cli-app"),
        named(result.stdout, "Job", "cli-accounts-migrate"),
    )


def test_sign_in_stays_off_by_default():
    app, job = resources(render())
    assert "KEEPLANE_CLI_OAUTH_ENABLED" not in app + job
    assert 'command: ["python", "/app/manage.py", "migrate", "--noinput"]' in job
    assert "register_cli_client" not in job


@pytest.mark.parametrize("managed", [False, True])
def test_enabled_sign_in_registers_both_clients_before_serving(managed):
    extra = (
        ("--set", "gateway.mode=managed", "--set", "gateway.install=true",
         "--set", "agentgateway-standalone.mode=readonly") if managed else ()
    )
    app, job = resources(render(
        "--set", "app.cliSignIn.enabled=true",
        "--set", "app.postgres.publicOrigin=https://unused.example.test", *extra,
    ))
    for value in (app, job):
        assert 'image: "' + IMAGE + '"' in value
        assert 'name: KEEPLANE_CLI_OAUTH_ENABLED\n              value: "1"' in value
        assert 'name: PUBLIC_ORIGIN\n              value: "https://keeplane.example.test"' in value
    commands = ["python /app/manage.py " + suffix for suffix in (
        "migrate --noinput", "register_cli_client\n", "register_cli_client --device",
    )]
    positions = [job.index(value) for value in commands]
    assert positions == sorted(positions)
    assert 'secretName: "keeplane-migration-db"' in job
    assert 'secretName: "keeplane-migration-db"' not in app
    assert all(value not in app + job for value in (
        "RUNTIME_AUTHORIZER_KEY_FILE", "RUNTIME_GUARD_MANIFEST_FILE", "containerPort: 5000",
    ))


def test_external_migrations_remain_supported():
    result = render("--set", "app.cliSignIn.enabled=true",
                    "--set", "app.postgres.migration.enabled=false")
    app, job = resources(result)
    assert not job and "KEEPLANE_CLI_OAUTH_ENABLED" in app
    assert "register_cli_client" not in result.stdout


@pytest.mark.parametrize("extra", [
    ("--set", "app.cliSignIn.enabled=true", "--set", "app.postgres.enabled=false"),
    ("--set-string", "app.cliSignIn.enabled=true"),
    ("--set", "ingress.enabled=false", "--set", "app.postgres.publicOrigin=http://unsafe"),
])
def test_invalid_sign_in_settings_refuse_render(extra):
    assert render(*extra).returncode != 0
