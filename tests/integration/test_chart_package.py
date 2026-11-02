"""Check local Helm packaging behavior before touching a cluster."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
from tests.support.helm import require_helm


ROOT = Path(__file__).resolve().parents[2]
HELM = require_helm()
CHART = "deploy/helm/keeplane"


def gateway_key_env(secret):
    """The two extraEnv entries the chart requires from gateway.keysSecret."""
    return [
        {
            "name": "GATEWAY_" + role + "_KEY_HASH",
            "valueFrom": {
                "secretKeyRef": {"name": secret, "key": role.lower() + "-key-hash"}
            },
        }
        for role in ("RUNTIME", "ADMIN")
    ]


def gateway_key_args(secret):
    """Helm arguments that give a managed gateway its key Secret."""
    return (
        "--set",
        "gateway.keysSecret=" + secret,
        "--set-json",
        "agentgateway-standalone.extraEnv=" + json.dumps(gateway_key_env(secret)),
    )


def run(*args):
    return subprocess.run(
        (HELM, *args), cwd=ROOT, text=True, capture_output=True, timeout=30
    )


def manifests(output):
    return [part for part in output.split("---\n") if "kind:" in part]


def named(output, kind, name):
    return next(
        (
            part
            for part in manifests(output)
            if "kind: " + kind + "\n" in part and "name: " + name + "\n" in part
        ),
        "",
    )


def case(identifier, passed, observed):
    return {
        "case": identifier,
        "verdict": "pass" if passed else "fail",
        "observed": observed,
    }


def run_cases():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Evidence output already exists")
    lint = run("lint", CHART, "-f", "deploy/local/values.yaml")
    managed = run("template", "keeplane", CHART, "-f", "deploy/local/values.yaml")
    existing_args = (
        "--set",
        "gateway.mode=existing",
        "--set",
        "gateway.install=false",
        "--set",
        "gateway.url=http://supplied-gateway:4000",
        "--set",
        "gateway.keysSecret=keeplane-gateway-keys",
    )
    existing = run("template", "keeplane-existing", CHART, *existing_args)
    managed_app = named(managed.stdout, "Deployment", "keeplane-app")
    existing_app = named(existing.stdout, "Deployment", "keeplane-existing-app")
    preflight = named(
        existing.stdout, "Job", "keeplane-existing-existing-gateway-preflight"
    )
    checks = [
        case(
            "PKG-01",
            lint.returncode == 0
            and managed.returncode == 0
            and bool(managed_app)
            and "automountServiceAccountToken: false" in managed_app
            and "type: RuntimeDefault" in managed_app
            and 'secretName: "keeplane-gateway-keys"' in managed_app
            and 'name: GATEWAY_MODE\n              value: "managed"' in managed_app
            and bool(named(managed.stdout, "Deployment", "keeplane")),
            {
                "lint_exit": lint.returncode,
                "render_exit": managed.returncode,
                "app_present": bool(managed_app),
            },
        ),
        case(
            "PKG-02",
            existing.returncode == 0
            and bool(existing_app)
            and bool(preflight)
            and 'secretName: "keeplane-gateway-keys"' in existing_app
            and 'name: GATEWAY_MODE\n              value: "existing"' in existing_app
            and 'secretName: "keeplane-gateway-keys"' in preflight
            and "automountServiceAccountToken: false" in preflight
            and "app: keeplane-existing-gateway-preflight" in preflight
            and not named(existing.stdout, "Deployment", "keeplane-existing"),
            {
                "render_exit": existing.returncode,
                "app_present": bool(existing_app),
                "preflight_present": bool(preflight),
            },
        ),
    ]
    sized = run(
        "template",
        "keeplane-existing",
        CHART,
        *existing_args,
        "--set",
        "app.imagePullSecrets[0].name=private-registry",
        "--set",
        "app.resources.requests.cpu=100m",
        "--set",
        "app.resources.requests.memory=128Mi",
    )
    sized_app = named(sized.stdout, "Deployment", "keeplane-existing-app")
    sized_job = named(
        sized.stdout, "Job", "keeplane-existing-existing-gateway-preflight"
    )
    checks.append(
        case(
            "PKG-03",
            sized.returncode == 0
            and all(
                "name: private-registry" in manifest
                and "cpu: 100m" in manifest
                and "memory: 128Mi" in manifest
                for manifest in (sized_app, sized_job)
            ),
            {
                "render_exit": sized.returncode,
                "app_settings": bool(sized_app),
                "preflight_settings": bool(sized_job),
            },
        )
    )
    invalid_existing = run(
        "template",
        "invalid",
        CHART,
        "--set",
        "gateway.mode=existing",
        "--set",
        "gateway.install=false",
    )
    invalid_managed = run(
        "template",
        "invalid",
        CHART,
        "--set",
        "gateway.mode=managed",
        "--set",
        "gateway.install=false",
    )
    missing_keys = run(
        "template", "invalid", CHART, "--set", "app.localTrial.enabled=true"
    )
    checks.append(
        case(
            "PKG-04",
            all(
                result.returncode != 0
                for result in (invalid_existing, invalid_managed, missing_keys)
            ),
            {
                "missing_url_exit": invalid_existing.returncode,
                "conflicting_mode_exit": invalid_managed.returncode,
                "missing_key_secret_exit": missing_keys.returncode,
            },
        )
    )
    policy = run(
        "template",
        "keeplane",
        CHART,
        "-f",
        "deploy/local/values.yaml",
        "--set",
        "networkPolicy.gatewayIngressEnabled=true",
    )
    policy_manifest = named(policy.stdout, "NetworkPolicy", "keeplane-gateway-ingress")
    invalid_existing_policy = run(
        "template",
        "keeplane-existing",
        CHART,
        *existing_args,
        "--set",
        "networkPolicy.gatewayIngressEnabled=true",
    )
    checks.append(
        case(
            "PKG-05",
            policy.returncode == 0
            and bool(policy_manifest)
            and "app.kubernetes.io/name: agentgateway-standalone" in policy_manifest
            and "app.kubernetes.io/instance: keeplane" in policy_manifest
            and "app: keeplane-app" in policy_manifest
            and "port: 4000" in policy_manifest
            and invalid_existing_policy.returncode != 0,
            {
                "managed_render_exit": policy.returncode,
                "policy_present": bool(policy_manifest),
                "existing_policy_exit": invalid_existing_policy.returncode,
            },
        )
    )
    edge_args = (
        "--set",
        "ingress.enabled=true",
        "--set",
        "ingress.className=nginx",
        "--set",
        "ingress.host=keeplane.example.test",
        "--set",
        "ingress.tlsSecretName=keeplane-tls",
    )
    managed_edge = run(
        "template",
        "keeplane",
        CHART,
        "-f",
        "deploy/local/values.yaml",
        "--set",
        "app.service.type=ClusterIP",
        *edge_args,
    )
    existing_edge = run(
        "template", "keeplane-existing", CHART, *existing_args, *edge_args
    )
    managed_ingress = named(managed_edge.stdout, "Ingress", "keeplane-app")
    existing_ingress = named(existing_edge.stdout, "Ingress", "keeplane-existing-app")
    edge_app = named(managed_edge.stdout, "Deployment", "keeplane-app")
    missing_tls = run(
        "template",
        "invalid",
        CHART,
        "-f",
        "deploy/local/values.yaml",
        "--set",
        "app.service.type=ClusterIP",
        *edge_args[:-2],
    )
    public_nodeport = run(
        "template", "invalid", CHART, "-f", "deploy/local/values.yaml", *edge_args
    )
    checks.append(
        case(
            "PKG-06",
            managed_edge.returncode == 0
            and existing_edge.returncode == 0
            and all(
                'ingressClassName: "nginx"' in manifest
                and 'host: "keeplane.example.test"' in manifest
                and 'secretName: "keeplane-tls"' in manifest
                for manifest in (managed_ingress, existing_ingress)
            )
            and "name: keeplane-app\n" in managed_ingress
            and "name: keeplane-existing-app\n" in existing_ingress
            and "name: keeplane\n" not in managed_ingress
            and 'value: "https://keeplane.example.test"' in edge_app
            and missing_tls.returncode != 0
            and public_nodeport.returncode != 0,
            {
                "managed_render_exit": managed_edge.returncode,
                "existing_render_exit": existing_edge.returncode,
                "missing_tls_exit": missing_tls.returncode,
                "public_nodeport_exit": public_nodeport.returncode,
            },
        )
    )
    protected_lint = run("lint", CHART, "-f", "deploy/local/existing-values.yaml")
    protected_existing = run(
        "template",
        "keeplane-existing",
        CHART,
        "-f",
        "deploy/local/existing-values.yaml",
    )
    protected_app = named(
        protected_existing.stdout, "Deployment", "keeplane-existing-app"
    )
    protected_service = named(
        protected_existing.stdout, "Service", "keeplane-existing-app"
    )
    checks.append(
        case(
            "PKG-07",
            protected_lint.returncode == 0
            and protected_existing.returncode == 0
            and bool(protected_app)
            and "python /app/manage.py migrate --noinput" in protected_app
            and "import_preview" not in protected_app
            and 'value: "http://127.0.0.1:13001"' in protected_app
            and "secretName: keeplane-first-admin" in protected_app
            and "type: ClusterIP" in protected_service
            and bool(
                named(
                    protected_existing.stdout,
                    "PersistentVolumeClaim",
                    "keeplane-existing-state",
                )
            )
            and not named(protected_existing.stdout, "Deployment", "keeplane-existing"),
            {
                "lint_exit": protected_lint.returncode,
                "render_exit": protected_existing.returncode,
                "app_present": bool(protected_app),
                "state_pvc_present": bool(
                    named(
                        protected_existing.stdout,
                        "PersistentVolumeClaim",
                        "keeplane-existing-state",
                    )
                ),
            },
        )
    )
    supplied = run(
        "template",
        "supplied-gateway",
        "deploy/helm/keeplane/charts/agentgateway-standalone-v1.6.0.tgz",
        "-f",
        "deploy/local/supplied-gateway-values.yaml",
    )
    db_fixture = (ROOT / "deploy/local/postgres-fixture.yaml").read_text()
    # The managed gateway serves from the StatefulSet copies; the bundled
    # chart's zero-replica Deployment must carry the same wiring.
    gateway_workloads = (
        (managed, "keeplane", "Deployment", "keeplane"),
        (managed, "keeplane", "StatefulSet", "keeplane-gateway"),
        (supplied, "supplied-gateway", "Deployment", "supplied-gateway"),
    )
    secret_wiring = all(
        "${KEEPLANE_DB_PASSWORD}" in named(result.stdout, "ConfigMap", config + "-config")
        and "local-test-only" not in result.stdout
        and "name: KEEPLANE_DB_PASSWORD" in named(result.stdout, kind, name)
        and "name: keeplane-gateway-db" in named(result.stdout, kind, name)
        and "key: password" in named(result.stdout, kind, name)
        for result, config, kind, name in gateway_workloads
    )
    checks.append(
        case(
            "PKG-08",
            supplied.returncode == 0
            and secret_wiring
            and "secretKeyRef:" in db_fixture
            and "name: keeplane-gateway-db" in db_fixture
            and "local-test-only" not in db_fixture
            and "KEEPLANE_DB_PASSWORD" not in existing.stdout
            and "keeplane-gateway-db" not in existing.stdout,
            {
                "supplied_render_exit": supplied.returncode,
                "both_gateway_passwords_secret_backed": secret_wiring,
                "existing_app_has_database_credentials": "KEEPLANE_DB_PASSWORD"
                in existing.stdout,
            },
        )
    )
    report = {
        "suite": "Keeplane local Helm packaging",
        "results": checks,
        "release_package_approved": False,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(any(row["verdict"] == "fail" for row in checks))


if __name__ == "__main__":
    sys.exit(run_cases())


def test_chart_package(monkeypatch, report_file, request, capsys):
    arguments = [__file__, "--output", str(report_file)]
    monkeypatch.setattr("sys.argv", arguments)
    assert run_cases() in (None, 0)
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    verify_cases(__file__, output.out, globals().get("REPORT", report_file))
