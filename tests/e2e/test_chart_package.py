"""Check local Helm packaging behavior before touching a cluster."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
HELM = os.environ.get("KEEPLANE_HELM_BIN") or shutil.which("helm") or "/private/tmp/keeplane-helm/darwin-amd64/helm"
CHART = "deploy/helm/keeplane"


def run(*args):
    return subprocess.run((HELM, *args), cwd=ROOT, text=True,
                          capture_output=True, timeout=30)


def manifests(output):
    return [part for part in output.split("---\n") if "kind:" in part]


def named(output, kind, name):
    return next((part for part in manifests(output)
                 if "kind: " + kind + "\n" in part and "name: " + name + "\n" in part), "")


def case(identifier, passed, observed):
    return {"case": identifier, "verdict": "pass" if passed else "fail", "observed": observed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Evidence output already exists")
    lint = run("lint", CHART, "-f", "deploy/local/values.yaml")
    managed = run("template", "keeplane", CHART, "-f", "deploy/local/values.yaml")
    existing_args = ("--set", "gateway.mode=existing", "--set", "gateway.install=false",
                     "--set", "gateway.url=http://supplied-gateway:4000",
                     "--set", "gateway.keysSecret=keeplane-gateway-keys")
    existing = run("template", "keeplane-existing", CHART, *existing_args)
    managed_app = named(managed.stdout, "Deployment", "keeplane-app")
    existing_app = named(existing.stdout, "Deployment", "keeplane-existing-app")
    preflight = named(existing.stdout, "Job", "keeplane-existing-existing-gateway-preflight")
    checks = [case("PKG-01", lint.returncode == 0 and managed.returncode == 0
                   and bool(managed_app) and "automountServiceAccountToken: false" in managed_app
                   and "type: RuntimeDefault" in managed_app
                   and "secretName: \"keeplane-gateway-keys\"" in managed_app
                   and bool(named(managed.stdout, "Deployment", "keeplane")),
                   {"lint_exit": lint.returncode, "render_exit": managed.returncode,
                    "app_present": bool(managed_app)}),
              case("PKG-02", existing.returncode == 0 and bool(existing_app) and bool(preflight)
                   and "secretName: \"keeplane-gateway-keys\"" in existing_app
                   and "secretName: \"keeplane-gateway-keys\"" in preflight
                   and "automountServiceAccountToken: false" in preflight
                   and not named(existing.stdout, "Deployment", "keeplane-existing"),
                   {"render_exit": existing.returncode, "app_present": bool(existing_app),
                    "preflight_present": bool(preflight)} )]
    sized = run("template", "keeplane-existing", CHART, *existing_args,
                "--set", "app.imagePullSecrets[0].name=private-registry",
                "--set", "app.resources.requests.cpu=100m",
                "--set", "app.resources.requests.memory=128Mi")
    sized_app = named(sized.stdout, "Deployment", "keeplane-existing-app")
    sized_job = named(sized.stdout, "Job", "keeplane-existing-existing-gateway-preflight")
    checks.append(case("PKG-03", sized.returncode == 0 and all(
        "name: private-registry" in manifest and "cpu: 100m" in manifest
        and "memory: 128Mi" in manifest for manifest in (sized_app, sized_job)),
        {"render_exit": sized.returncode, "app_settings": bool(sized_app),
         "preflight_settings": bool(sized_job)}))
    invalid_existing = run("template", "invalid", CHART, "--set", "gateway.mode=existing",
                           "--set", "gateway.install=false")
    invalid_managed = run("template", "invalid", CHART, "--set", "gateway.mode=managed",
                          "--set", "gateway.install=false")
    missing_keys = run("template", "invalid", CHART, "--set", "app.localTrial.enabled=true")
    checks.append(case("PKG-04", all(result.returncode != 0 for result in
                     (invalid_existing, invalid_managed, missing_keys)),
                       {"missing_url_exit": invalid_existing.returncode,
                        "conflicting_mode_exit": invalid_managed.returncode,
                        "missing_key_secret_exit": missing_keys.returncode}))
    policy = run("template", "keeplane", CHART, "-f", "deploy/local/values.yaml",
                 "--set", "networkPolicy.gatewayIngressEnabled=true")
    policy_manifest = named(policy.stdout, "NetworkPolicy", "keeplane-gateway-ingress")
    invalid_existing_policy = run("template", "keeplane-existing", CHART, *existing_args,
                                  "--set", "networkPolicy.gatewayIngressEnabled=true")
    checks.append(case("PKG-05", policy.returncode == 0 and bool(policy_manifest)
                       and "app.kubernetes.io/name: agentgateway-standalone" in policy_manifest
                       and "app.kubernetes.io/instance: keeplane" in policy_manifest
                       and "app: keeplane-app" in policy_manifest
                       and "port: 4000" in policy_manifest
                       and invalid_existing_policy.returncode != 0,
                       {"managed_render_exit": policy.returncode,
                        "policy_present": bool(policy_manifest),
                        "existing_policy_exit": invalid_existing_policy.returncode}))
    edge_args = ("--set", "ingress.enabled=true", "--set", "ingress.className=nginx",
                 "--set", "ingress.host=keeplane.example.test",
                 "--set", "ingress.tlsSecretName=keeplane-tls")
    managed_edge = run("template", "keeplane", CHART, "-f", "deploy/local/values.yaml",
                       "--set", "app.service.type=ClusterIP", *edge_args)
    existing_edge = run("template", "keeplane-existing", CHART, *existing_args, *edge_args)
    managed_ingress = named(managed_edge.stdout, "Ingress", "keeplane-app")
    existing_ingress = named(existing_edge.stdout, "Ingress", "keeplane-existing-app")
    edge_app = named(managed_edge.stdout, "Deployment", "keeplane-app")
    missing_tls = run("template", "invalid", CHART, "-f", "deploy/local/values.yaml",
                      "--set", "app.service.type=ClusterIP", *edge_args[:-2])
    public_nodeport = run("template", "invalid", CHART, "-f", "deploy/local/values.yaml",
                          *edge_args)
    checks.append(case("PKG-06", managed_edge.returncode == 0
                       and existing_edge.returncode == 0
                       and all("ingressClassName: \"nginx\"" in manifest
                               and "host: \"keeplane.example.test\"" in manifest
                               and "secretName: \"keeplane-tls\"" in manifest
                               for manifest in (managed_ingress, existing_ingress))
                       and "name: keeplane-app\n" in managed_ingress
                       and "name: keeplane-existing-app\n" in existing_ingress
                       and "name: keeplane\n" not in managed_ingress
                       and "value: \"https://keeplane.example.test\"" in edge_app
                       and missing_tls.returncode != 0 and public_nodeport.returncode != 0,
                       {"managed_render_exit": managed_edge.returncode,
                        "existing_render_exit": existing_edge.returncode,
                        "missing_tls_exit": missing_tls.returncode,
                        "public_nodeport_exit": public_nodeport.returncode}))
    report = {"suite": "Keeplane local Helm packaging", "results": checks,
              "release_package_approved": False}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(any(row["verdict"] == "fail" for row in checks))


if __name__ == "__main__":
    sys.exit(main())
