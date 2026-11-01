"""The chart stays in one namespace, and the example installer Role covers it.

Cases are described in chart-namespace-permissions-cases.md. NSP-04 reads only
the example Role and runs everywhere; the other cases render the chart with
Helm and are skipped when Helm is missing.
"""

import json
from pathlib import Path
import re
import subprocess

import pytest

from tests.support.helm import require_helm


ROOT = Path(__file__).resolve().parents[2]
CHART = "deploy/helm/keeplane"
ROLE_FILE = ROOT / "deploy/examples/installer-role.yaml"
CATALOG = Path(__file__).with_name("chart-namespace-permissions-cases.md")
NAMESPACE = "keeplane-permissions"
IMAGE = "registry.example.test/keeplane@sha256:" + "a" * 64

# Every kind the chart may render, with the API group and resource the
# installer Role must grant for it. All are namespaced.
KIND_RESOURCE = {
    ("v1", "ConfigMap"): ("", "configmaps"),
    ("v1", "PersistentVolumeClaim"): ("", "persistentvolumeclaims"),
    ("v1", "Service"): ("", "services"),
    ("v1", "ServiceAccount"): ("", "serviceaccounts"),
    ("apps/v1", "Deployment"): ("apps", "deployments"),
    ("apps/v1", "StatefulSet"): ("apps", "statefulsets"),
    ("batch/v1", "Job"): ("batch", "jobs"),
    ("policy/v1", "PodDisruptionBudget"): ("policy", "poddisruptionbudgets"),
    ("networking.k8s.io/v1", "Ingress"): ("networking.k8s.io", "ingresses"),
    ("networking.k8s.io/v1", "NetworkPolicy"): ("networking.k8s.io", "networkpolicies"),
}
# Kinds the chart must never render: cluster-scoped objects, and namespaced
# RBAC that would hand out Kubernetes API permissions.
FORBIDDEN_KINDS = {
    "APIService", "CSIDriver", "ClusterRole", "ClusterRoleBinding",
    "CustomResourceDefinition", "IngressClass", "MutatingWebhookConfiguration",
    "Namespace", "Node", "PersistentVolume", "PriorityClass", "Role",
    "RoleBinding", "RuntimeClass", "StorageClass", "ValidatingAdmissionPolicy",
    "ValidatingAdmissionPolicyBinding", "ValidatingWebhookConfiguration",
    "VolumeAttachment",
}
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "Job", "DaemonSet", "CronJob", "Pod",
                  "ReplicaSet"}

LIFECYCLE = {"get", "list", "watch", "create", "update", "patch", "delete"}
READ = {"get", "list", "watch"}
# Read access helm --wait and troubleshooting need beyond the chart's objects.
FOLLOW = {("", "pods"): READ, ("", "events"): READ, ("", "pods/log"): {"get"},
          ("apps", "replicasets"): READ}
# Never acceptable in the installer Role.
DANGEROUS_VERBS = {"*", "escalate", "bind", "impersonate", "approve", "sign"}
CLUSTER_SCOPED_RESOURCES = {
    "namespaces", "nodes", "persistentvolumes", "storageclasses", "ingressclasses",
    "priorityclasses", "customresourcedefinitions", "clusterroles",
    "clusterrolebindings", "mutatingwebhookconfigurations",
    "validatingwebhookconfigurations", "apiservices", "runtimeclasses",
    "csidrivers", "volumeattachments", "certificatesigningrequests",
}


# ---------------------------------------------------------------------------
# Reading rendered manifests and the Role file without a YAML dependency.

def documents(text):
    return [part for part in re.split(r"^---\s*$", text, flags=re.M)
            if re.search(r"^kind: ", part, re.M)]


def top(document, key):
    match = re.search(r"^" + key + r": \"?([^\"\n]+?)\"?\s*$", document, re.M)
    return match.group(1) if match else None


def metadata(document, key):
    """A direct child of the top-level metadata block."""
    lines = document.splitlines()
    try:
        start = lines.index("metadata:")
    except ValueError:
        return None
    for line in lines[start + 1:]:
        if line and not line.startswith(" "):
            break
        match = re.fullmatch(r"  " + key + r": \"?([^\"]+?)\"?\s*", line)
        if match:
            return match.group(1)
    return None


def source(document):
    match = re.search(r"^# Source: (\S+)", document, re.M)
    return match.group(1) if match else None


def flow_list(text):
    inner = text.strip()
    assert inner.startswith("[") and inner.endswith("]"), "Write Role lists as [a, b]: " + text
    return [item.strip().strip("\"'") for item in inner[1:-1].split(",") if item.strip()]


def role_documents():
    return documents(ROLE_FILE.read_text())


def role_rules():
    """The Role's rules as (apiGroups, resources, verbs) triples."""
    roles = [doc for doc in role_documents() if top(doc, "kind") == "Role"]
    assert len(roles) == 1, "The example must hold exactly one Role"
    lines = roles[0].splitlines()
    start = lines.index("rules:")
    rules, current = [], None
    for line in lines[start + 1:]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if not line.startswith(" "):
            break
        match = re.fullmatch(r"  (- |  )(apiGroups|resources|verbs): (.+)", line)
        assert match, "Unexpected Role rule line (only apiGroups, resources, verbs): " + line
        if match.group(1) == "- ":
            current = {}
            rules.append(current)
        assert current is not None and match.group(2) not in current, line
        current[match.group(2)] = flow_list(match.group(3))
    for rule in rules:
        assert set(rule) == {"apiGroups", "resources", "verbs"}, rule
    return [(rule["apiGroups"], rule["resources"], rule["verbs"]) for rule in rules]


def granted():
    """(group, resource) -> verbs granted by the Role."""
    found = {}
    for groups, resources, verbs in role_rules():
        for group in groups:
            for resource in resources:
                found.setdefault((group, resource), set()).update(verbs)
    return found


# ---------------------------------------------------------------------------
# Rendering every supported installation mode.

def secret_env(name, secret, key):
    return {"name": name, "valueFrom": {"secretKeyRef": {"name": secret, "key": key}}}


def postgres_values(mode):
    """PostgreSQL installation values, as in the installation reference."""
    values = {
        "app": {
            "image": IMAGE,
            "replicaCount": 2,
            "postgres": {
                "enabled": True,
                "host": "postgres.database.svc.cluster.local",
                "database": "keeplane",
                "user": "keeplane_app",
                "credentialsSecret": "keeplane-app-db",
                "identitySecret": "keeplane-identity",
                "caSecret": "keeplane-database-ca",
                "providerKeysClaim": "keeplane-provider-keys",
                "migration": {"user": "keeplane_migrate",
                              "credentialsSecret": "keeplane-migration-db"},
            },
        },
        "ingress": {"enabled": True, "className": "nginx",
                    "host": "keeplane.example.test", "tlsSecretName": "keeplane-tls"},
        "gateway": {"mode": "managed", "install": True,
                    "keysSecret": "keeplane-gateway-keys", "copies": 2},
        "networkPolicy": {"gatewayIngressEnabled": mode == "managed"},
        "agentgateway-standalone": {
            "database": {"postgres": {
                "url": "postgresql://keeplane:${KEEPLANE_DB_PASSWORD}"
                "@gateway-db.database.svc.cluster.local:5432/keeplane"}},
            "extraEnv": [
                secret_env("KEEPLANE_DB_PASSWORD", "keeplane-gateway-db", "password"),
                secret_env("GATEWAY_RUNTIME_KEY_HASH", "keeplane-gateway-keys",
                           "runtime-key-hash"),
                secret_env("GATEWAY_ADMIN_KEY_HASH", "keeplane-gateway-keys",
                           "admin-key-hash"),
            ],
            "extraVolumes": [{"name": "provider-keys", "persistentVolumeClaim":
                              {"claimName": "keeplane-provider-keys"}}],
            "extraVolumeMounts": [{"name": "provider-keys", "mountPath": "/provider-keys",
                                   "readOnly": True}],
            # Optional objects of the bundled chart, so they are covered too.
            "podDisruptionBudget": {"enabled": True},
            "gateway": {"extraServices": [{"name": "extra", "type": "ClusterIP",
                                           "ports": [{"name": "http", "port": 4000}]}]},
        },
    }
    if mode == "existing":
        values["gateway"].update(mode="existing", install=False,
                                 url="http://customer-gateway.gateway.svc.cluster.local:4000")
        values["agentgateway-standalone"] = {}
    return values


SIGN_IN = ("--set", "app.cliSignIn.enabled=true",
           "--set", "app.postgres.publicOrigin=https://unused.example.test")


def modes(files):
    """Every supported installation, as Helm arguments."""
    managed = ("-f", str(files["managed"]))
    existing = ("-f", str(files["existing"]))
    return {
        "managed-local": ("-f", "deploy/local/values.yaml"),
        "managed-postgres": managed,
        "managed-postgres-cli-sign-in": (*managed, *SIGN_IN),
        "existing-local": ("-f", "deploy/local/existing-values.yaml"),
        "existing-postgres": existing,
        "existing-postgres-cli-sign-in": (*existing, *SIGN_IN),
        "existing-postgres-example": ("-f", "deploy/postgres/values.example.yaml",
                                      "--set", "app.image=" + IMAGE),
    }


def refusals(files):
    """Bundled-chart options that would add other kinds or another namespace."""
    managed = ("-f", str(files["managed"]))
    return {
        "autoscaling": (*managed, "--set", "agentgateway-standalone.autoscaling.enabled=true"),
        "monitoring": (*managed, "--set", "agentgateway-standalone.monitoring.enabled=true",
                       "--set", "agentgateway-standalone.monitoring.podMonitor.enabled=true"),
        "namespace-override": (*managed, "--set",
                               "agentgateway-standalone.namespaceOverride=elsewhere"),
    }


def helm(binary, *args):
    return subprocess.run((binary, "template", "nsp", CHART, "--namespace", NAMESPACE, *args),
                          cwd=ROOT, text=True, capture_output=True, timeout=60)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    binary = require_helm()
    directory = tmp_path_factory.mktemp("namespace-permissions")
    files = {}
    for mode in ("managed", "existing"):
        files[mode] = directory / (mode + ".json")
        files[mode].write_text(json.dumps(postgres_values(mode)))
    results = {label: helm(binary, *args) for label, args in modes(files).items()}
    for label, result in results.items():
        assert result.returncode == 0, (label, result.stderr)
    refused = {label: helm(binary, *args) for label, args in refusals(files).items()}
    return {"modes": {label: r.stdout for label, r in results.items()}, "refused": refused}


def inventory(output):
    return [(top(doc, "apiVersion"), top(doc, "kind"), metadata(doc, "name"),
             metadata(doc, "namespace"), source(doc), doc) for doc in documents(output)]


# ---------------------------------------------------------------------------
# Cases.

def test_nsp_01_every_mode_renders_only_listed_namespaced_kinds(rendered):
    seen, problems, by_source = set(), [], {}
    for label, output in rendered["modes"].items():
        for api, kind, name, namespace, origin, _ in inventory(output):
            seen.add((api, kind))
            by_source.setdefault(origin, set()).add(kind)
            if kind in FORBIDDEN_KINDS or (api, kind) not in KIND_RESOURCE:
                problems.append(f"{label}: {api} {kind} {name} from {origin}")
            if namespace not in (None, NAMESPACE):
                problems.append(f"{label}: {kind} {name} targets namespace {namespace}")
    print(json.dumps({"rendered_kinds": sorted(f"{a} {k}" for a, k in seen),
                      "kinds_by_template": {s: sorted(k) for s, k in by_source.items()}},
                     indent=2))
    assert not problems, problems
    # Exactly the listed set: a new kind must be reviewed and added to the Role.
    assert seen == set(KIND_RESOURCE), sorted(set(KIND_RESOURCE) ^ seen)
    # The bundled gateway chart contributes only these kinds. Its own
    # disruption budget needs more than one replica of its Deployment, which
    # stays at zero; the chart's budget covers the gateway copies instead.
    bundled = set().union(*(kinds for origin, kinds in by_source.items()
                            if "charts/agentgateway-standalone/" in (origin or "")))
    assert bundled == {"ConfigMap", "Deployment", "Service", "ServiceAccount"}, bundled


def test_nsp_02_bundled_options_that_leave_the_namespace_are_refused(rendered):
    for label, result in rendered["refused"].items():
        assert result.returncode != 0, (label, "rendered")
        assert "agentgateway-standalone" in result.stderr, (label, result.stderr)


def test_nsp_03_pods_get_no_kubernetes_api_token(rendered):
    checked = {}
    for label, output in rendered["modes"].items():
        for _, kind, name, _, _, doc in inventory(output):
            if kind not in WORKLOAD_KINDS:
                continue
            replicas = re.search(r"^  replicas: (\d+)\s*$", doc, re.M)
            no_token = re.search(r"^\s+automountServiceAccountToken: false\s*$", doc, re.M)
            # The bundled gateway chart's own Deployment runs no pods; the
            # chart's StatefulSet runs the gateway copies instead.
            idle = kind == "Deployment" and replicas is not None and replicas.group(1) == "0"
            checked[f"{label}/{kind}/{name}"] = "no token" if no_token else (
                "runs no pods" if idle else "token mounted")
    print(json.dumps(checked, indent=2))
    assert checked and all(state != "token mounted" for state in checked.values()), checked
    copies = [key for key in checked if key.endswith("/StatefulSet/nsp-gateway")]
    idle = [key for key, state in checked.items() if state == "runs no pods"]
    assert copies and all(checked[key] == "no token" for key in copies)
    assert all(key.endswith("/Deployment/nsp") for key in idle), idle


def test_nsp_04_installer_role_is_namespaced_and_bounded():
    kinds = [top(doc, "kind") for doc in role_documents()]
    assert sorted(kinds) == ["Role", "RoleBinding"], kinds
    for doc in role_documents():
        assert top(doc, "apiVersion") == "rbac.authorization.k8s.io/v1"
        assert metadata(doc, "namespace"), "Each object names its namespace"
    binding = next(doc for doc in role_documents() if top(doc, "kind") == "RoleBinding")
    assert re.search(r"^roleRef:\n(?:  .*\n)*?  kind: Role\n", binding, re.M), binding
    assert "ClusterRole" not in binding
    allowed_writes = {resource for resource in KIND_RESOURCE.values()} | {("", "secrets")}
    for group_resource, verbs in granted().items():
        group, resource = group_resource
        assert "*" not in (group, resource), group_resource
        assert not verbs & DANGEROUS_VERBS, (group_resource, verbs)
        assert verbs <= LIFECYCLE, (group_resource, verbs)
        assert group != "rbac.authorization.k8s.io", group_resource
        assert resource not in CLUSTER_SCOPED_RESOURCES, group_resource
        if verbs - READ:
            assert group_resource in allowed_writes, ("writes beyond the chart", group_resource)
        else:
            assert group_resource in FOLLOW or group_resource in allowed_writes, group_resource
    for group_resource, verbs in FOLLOW.items():
        assert verbs <= granted().get(group_resource, set()), group_resource


def test_nsp_05_role_covers_every_rendered_kind(rendered):
    grants = granted()
    needed = {KIND_RESOURCE[(api, kind)]
              for output in rendered["modes"].values()
              for api, kind, *_ in inventory(output) if (api, kind) in KIND_RESOURCE}
    # Helm keeps its release records in Secrets in the release namespace.
    needed.add(("", "secrets"))
    missing = {f"{g or 'core'}/{r}": sorted(LIFECYCLE - grants.get((g, r), set()))
               for g, r in sorted(needed) if not LIFECYCLE <= grants.get((g, r), set())}
    assert not missing, missing


def test_catalog_lists_exactly_these_cases():
    listed = re.findall(r"^\| (NSP-\d+) \|", CATALOG.read_text(), re.M)
    defined = sorted({name.split("_")[2] for name in globals()
                      if re.fullmatch(r"test_nsp_\d+_.+", name)})
    assert listed == ["NSP-" + number for number in defined], (listed, defined)
