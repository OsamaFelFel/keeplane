"""The chart repairs only provider storage and refuses a widening gateway mount."""

import json

import pytest

from tests.integration.test_chart_package import CHART, named, run


@pytest.mark.parametrize("profile", ["managed", "existing", "postgres"])
def test_provider_initializer_is_scoped_and_before_application(profile, tmp_path):
    if profile == "postgres":
        values = {
            "app": {
                "image": "registry.test/app@sha256:" + "a" * 64,
                "postgres": {
                    "enabled": True,
                    "host": "db",
                    "database": "keeplane",
                    "user": "app",
                    "credentialsSecret": "app-db",
                    "identitySecret": "identity",
                    "caSecret": "ca",
                    "publicOrigin": "https://keeplane.test",
                    "providerKeysClaim": "provider-keys",
                    "migration": {"user": "migrate", "credentialsSecret": "migrate-db"},
                },
            },
            "gateway": {"keysSecret": "gateway-keys"},
            "agentgateway-standalone": {"mode": "readonly"},
        }
        path = tmp_path / "values.yaml"
        path.write_text(json.dumps(values))
    else:
        path = "deploy/local/" + (
            "existing-values.yaml" if profile == "existing" else "values.yaml"
        )
    result = run("template", "keeplane", CHART, "-f", str(path))
    assert result.returncode == 0, result.stderr
    app = named(result.stdout, "Deployment", "keeplane-app")
    assert "fsGroup: 65532" in app
    initializer = app.split("initContainers:\n", 1)[1].split("      containers:\n")[0]
    initializer = initializer.split("        - name: migrate-local-database")[0]
    assert initializer.startswith("        - name: prepare-provider-keys\n")
    assert "command: [python, /app/prepare_provider_volume.py]" in initializer
    mounts = initializer.split("volumeMounts:\n")[1].split(
        "          securityContext:"
    )[0]
    assert mounts.splitlines() == [
        "            - name: provider-keys",
        "              mountPath: /provider-keys",
    ]
    assert "env:" not in initializer
    for setting in (
        "runAsNonRoot: false",
        "runAsUser: 0",
        "runAsGroup: 0",
        "privileged: false",
        "allowPrivilegeEscalation: false",
        "readOnlyRootFilesystem: true",
        "drop: [ALL]",
        "add: [CHOWN, FOWNER, DAC_OVERRIDE]",
    ):
        assert setting in initializer
    gateway = named(result.stdout, "Deployment", "keeplane")
    assert "fsGroup: 65532" not in gateway


def test_managed_gateway_cannot_reset_provider_permissions():
    result = run(
        "template",
        "keeplane",
        CHART,
        "-f",
        "deploy/local/values.yaml",
        "--set",
        "agentgateway-standalone.podSecurityContext.fsGroup=65532",
    )
    assert result.returncode != 0
    assert "Leave the managed gateway fsGroup unset" in result.stderr
