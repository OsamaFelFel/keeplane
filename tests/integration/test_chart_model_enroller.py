"""Render the model enroller and protected runtime on each managed gateway copy (ADR 027).

Cases ME-01 to ME-15 in chart-model-enroller-cases.md. All but ME-10 render
the chart with Helm and are skipped when Helm is missing; ME-10 reads only the
values file and the guides and always runs.
"""

import copy
import hashlib
import json
from pathlib import Path
import re

import pytest
from prepare_enroller_files import Unprepared, install_runtime, runtime_plan

ROOT = Path(__file__).resolve().parents[2]
VALUES = ROOT / "deploy/helm/keeplane/values.yaml"
REFERENCE = ROOT / "docs/guide/kubernetes-installation-reference.md"
ROLES_GUIDE = ROOT / "docs/guide/guard-status-roles.md"
ARCHITECTURE = ROOT / "docs/architecture/runtime-authorization.md"
RELEASE = "pg"
CHECK = "KEEPLANE_GUARD_STATUS_CHECK"
APPROVALS_SECRET = "keeplane-enroller-db"
STATUS_SECRET = "keeplane-guard-status-db"
FILES = "/run/keeplane-enroller/files"
APP_DATABASE = [{"cidr": "10.20.0.5/32", "ports": [5432]}]
GATEWAY_DATABASE = [{"cidr": "10.20.0.6/32", "ports": [5432]}]
MODELS = [{"cidr": "203.0.113.0/24", "ports": [443]}]
# The refusal this chart carried until it installed the protected runtime.
NOT_YET = "templates/checks/first/protected-runtime.yaml"
KEYS_SECRET = "keeplane-gateway-keys"
BASE = "KEEPLANE_ENROLLER_RUNTIME_BASE"
PUBLIC_ENTRY = {"namespaceSelector": {"kubernetes.io/metadata.name": "ingress-nginx"}}
GATEWAY_DATABASE_URL = ("postgresql://keeplane:${KEEPLANE_DB_PASSWORD}"
                        "@gateway-db.database.svc.cluster.local:5432/keeplane")


def with_enroller(values, copies=None, **settings):
    """values with the enroller on, in the form the installation reference shows."""
    values = copy.deepcopy(values)
    copies = copies or values["gateway"].get("copies", 2)
    values["gateway"]["copies"] = copies
    values["gateway"]["enroller"] = {
        "enabled": True,
        "approvalsUser": "keeplane_enroller",
        "approvalsSecret": APPROVALS_SECRET,
        "statusRoles": [f"keeplane_status_{index}" for index in range(copies)],
        "statusSecret": STATUS_SECRET,
        **settings,
    }
    # With the gateway ingress policy, the enroller needs the public entry
    # that may reach the protected port (chart-protected-access-cases.md).
    policy = values.setdefault("networkPolicy", {})
    if policy.get("gatewayIngressEnabled") and not policy.get("publicEntry"):
        policy["publicEntry"] = PUBLIC_ENTRY
    return values


@pytest.fixture(scope="module")
def chart():
    """Rendered chart helpers; skips without Helm, as the other chart checks do."""
    from tests.integration import test_chart_installation_shape as shape

    return shape


@pytest.fixture(scope="module")
def policy():
    from tests.integration import test_chart_network_policies as policies

    return policies


@pytest.fixture
def make(chart, tmp_path):
    def build(values=None, *args, release=RELEASE):
        files = []
        if values is not None:
            path = tmp_path / f"values-{len(list(tmp_path.iterdir()))}.json"
            path.write_text(json.dumps(values))
            files = ["-f", str(path)]
        return chart.run("template", release, chart.CHART, "--namespace", "keeplane",
                         *files, *args)
    return build


def rendered(result):
    assert result.returncode == 0, result.stderr
    return result.stdout


def refused(result, *phrases):
    assert result.returncode != 0, "rendered"
    for phrase in phrases:
        assert phrase in result.stderr, (phrase, result.stderr)


def managed(chart):
    return chart.postgres_values("managed")


def copies_of(chart, policy, output):
    document = next(doc for doc in chart.of_kind(output, "StatefulSet")
                    if chart.name_of(doc) == f"{RELEASE}-gateway")
    return policy.parse(document)


def pod(parsed):
    return parsed["spec"]["template"]["spec"]


def named(entries, name):
    return next(entry for entry in entries if entry["name"] == name)


def env_map(container):
    return {entry["name"]: entry.get("value", entry.get("valueFrom"))
            for entry in container.get("env", [])}


def app_env(chart, output):
    app = next(doc for doc in chart.of_kind(output, "Deployment")
               if chart.name_of(doc) == f"{RELEASE}-app")
    container = next(item for item in chart.containers(app)
                     if chart.scalar(item, "name") == "app")
    return chart.env(container)


def migration(chart, output):
    return next(doc for doc in chart.of_kind(output, "Job")
                if chart.name_of(doc) == f"{RELEASE}-accounts-migrate")


def kinds(chart, output):
    return sorted((chart.kind_of(doc), chart.name_of(doc))
                  for doc in chart.manifests(output))


# --- Cases -------------------------------------------------------------------------


def test_me_01_off_by_default_nothing_changes(chart, make):
    installs = {
        "postgres-managed": (managed(chart),),
        "postgres-existing": (chart.postgres_values("existing"),),
        "local-managed": (None, "-f", "deploy/local/values.yaml"),
        "local-existing": (None, "-f", "deploy/local/existing-values.yaml"),
    }
    for label, args in installs.items():
        output = rendered(make(*args))
        for absent in (CHECK, "model-enroller", "keeplane-guard", "KEEPLANE_ENROLLER_",
                       "configure_guard_status_access", "/installed",
                       "RUNTIME_AUTHORIZER_KEY_FILE", "callback-key"):
            assert absent not in output, (label, absent)
        # Without the enroller, a managed copy starts from the ConfigMap as before.
        if label.endswith("-managed"):
            assert "- /config/config.yaml" in output, label


def test_me_02_each_copy_runs_a_private_enroller_beside_its_gateway(chart, policy, make):
    before = copies_of(chart, policy, rendered(make(managed(chart))))
    after = copies_of(chart, policy, rendered(make(with_enroller(managed(chart)))))
    spec = pod(after)
    assert [item["name"] for item in spec["containers"]] == ["agentgateway", "model-enroller"]
    assert [item["name"] for item in spec["initContainers"]] == ["prepare-model-enroller"]
    # One Pod per copy, as before: the enroller shares each copy's network
    # namespace and the Pod still gets no Kubernetes API token.
    assert after["spec"]["replicas"] == before["spec"]["replicas"] == 2
    assert spec["automountServiceAccountToken"] is False
    assert "hostNetwork" not in spec and "shareProcessNamespace" not in spec
    enroller = named(spec["containers"], "model-enroller")
    assert enroller["image"] == chart.IMAGE
    assert enroller["command"] == ["python", "/app/manage.py", "run_model_enroller",
                                   "--callback-host", f"{RELEASE}-app:3000"]
    for container in (enroller, named(spec["initContainers"], "prepare-model-enroller")):
        assert "ports" not in container and "readinessProbe" not in container
        assert container["securityContext"] == {
            "runAsNonRoot": True, "runAsUser": 65532, "runAsGroup": 65532,
            "privileged": False, "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        }
        assert container["resources"] == {
            "requests": {"cpu": "25m", "memory": "128Mi"},
            "limits": {"cpu": "500m", "memory": "384Mi"},
        }
    values = env_map(enroller)
    assert values["GATEWAY_URL"] == "http://127.0.0.1:4000"
    assert values["KEEPLANE_DATABASE_READ_ONLY"] == "1"
    assert values["KEEPLANE_DATABASE_USER"] == "keeplane_enroller"
    assert values["KEEPLANE_GATEWAY_COPY"] == {"fieldRef": {"fieldPath": "metadata.name"}}
    assert values["KEEPLANE_DATABASE_SSLMODE"] == "verify-full"
    # Every credential is a file the init step wrote; none is in its settings.
    assert {name: value for name, value in values.items() if name.endswith("_FILE")} == {
        "GATEWAY_ADMIN_KEY_FILE": f"{FILES}/gateway-admin-key",
        "GATEWAY_RUNTIME_KEY_FILE": f"{FILES}/gateway-runtime-key",
        "RUNTIME_AUTHORIZER_KEY_FILE": "/installed/callback-key",
        "RUNTIME_GUARD_MANIFEST_FILE": "/installed/manifest.json",
        "KEEPLANE_DATABASE_SSLROOTCERT_FILE": f"{FILES}/database-ca.crt",
        "KEEPLANE_DATABASE_PASSWORD_FILE": f"{FILES}/approvals-password",
        "KEEPLANE_GUARD_STATUS_DATABASE_USER_FILE": f"{FILES}/status-user",
        "KEEPLANE_GUARD_STATUS_DATABASE_PASSWORD_FILE": f"{FILES}/status-password",
        "DJANGO_SECRET_KEY_FILE": f"{FILES}/signing-secret",
    }
    assert not any("secretKeyRef" in json.dumps(value) for value in values.values())
    assert enroller["volumeMounts"] == [
        {"name": "keeplane-guard", "mountPath": "/installed", "subPath": "installed"},
        {"name": "keeplane-enroller-files", "mountPath": "/run/keeplane-enroller",
         "readOnly": True},
        {"name": "keeplane-enroller-provider-keys", "mountPath": "/provider-keys",
         "readOnly": True},
    ]


def test_me_03_the_gateway_reads_the_guard_and_gets_nothing_else(chart, policy, make):
    before = pod(copies_of(chart, policy, rendered(make(managed(chart)))))
    output = rendered(make(with_enroller(managed(chart))))
    after = pod(copies_of(chart, policy, output))
    # The app never mounts the guard, or anything at /installed.
    app = next(doc for doc in chart.of_kind(output, "Deployment")
               if chart.name_of(doc) == f"{RELEASE}-app")
    assert "keeplane-guard" not in app and "/installed" not in app
    assert "keeplane-enroller" not in app
    gateway_before = named(before["containers"], "agentgateway")
    gateway_after = named(after["containers"], "agentgateway")
    added = [mount for mount in gateway_after["volumeMounts"]
             if mount not in gateway_before["volumeMounts"]]
    assert added == [{"name": "keeplane-guard", "mountPath": "/installed",
                      "subPath": "installed", "readOnly": True}]
    # It starts from the protected runtime in the guard, not the ConfigMap.
    assert gateway_before["args"] == ["-f", "/config/config.yaml"]
    assert gateway_after["args"] == ["-f", "/installed/gateway.json"]
    # Same settings, image and security: no database credential or key file.
    changed = ("volumeMounts", "args")
    assert {key: value for key, value in gateway_after.items() if key not in changed} \
        == {key: value for key, value in gateway_before.items() if key not in changed}
    # No fsGroup appears and no Secret volume is added; the enroller's files
    # are in memory and only its own containers mount them.
    assert after.get("securityContext") == before.get("securityContext")
    assert "fsGroup" not in json.dumps(after.get("securityContext", {}))
    volumes = {volume["name"]: volume for volume in after["volumes"]}
    assert not any("secret" in volume or "projected" in volume for volume in volumes.values())
    assert volumes["keeplane-guard"] == {"name": "keeplane-guard",
                                         "emptyDir": {"sizeLimit": "16Mi"}}
    assert volumes["keeplane-enroller-files"] == {
        "name": "keeplane-enroller-files",
        "emptyDir": {"medium": "Memory", "sizeLimit": "1Mi"}}
    assert volumes["keeplane-enroller-provider-keys"] == {
        "name": "keeplane-enroller-provider-keys",
        "persistentVolumeClaim": {"claimName": "keeplane-provider-keys", "readOnly": True}}
    users = {name: [item["name"] for item in after["initContainers"] + after["containers"]
                    if any(mount["name"] == name for mount in item.get("volumeMounts", []))]
             for name in volumes}
    assert users["keeplane-enroller-files"] == ["prepare-model-enroller", "model-enroller"]
    assert users["keeplane-guard"] == ["prepare-model-enroller", "agentgateway",
                                       "model-enroller"]
    assert users["keeplane-enroller-provider-keys"] == ["model-enroller"]


@pytest.mark.parametrize("copies", [1, 2, 3])
def test_me_04_only_the_init_step_reads_the_installer_made_secrets(chart, policy, make, copies):
    output = rendered(make(with_enroller(managed(chart), copies=copies)))
    spec = pod(copies_of(chart, policy, output))
    init = named(spec["initContainers"], "prepare-model-enroller")
    assert init["command"] == ["python", "-I", "/app/prepare_enroller_files.py"]
    references = {entry["name"]: (entry["valueFrom"]["secretKeyRef"]["name"],
                                  entry["valueFrom"]["secretKeyRef"]["key"])
                  for entry in init["env"] if "secretKeyRef" in entry.get("valueFrom", {})}
    assert references == {
        "KEEPLANE_ENROLLER_APPROVALS_PASSWORD": (APPROVALS_SECRET, "password"),
        **{f"KEEPLANE_ENROLLER_STATUS_PASSWORD_{index}": (STATUS_SECRET,
                                                         f"copy-{index}-password")
           for index in range(copies)},
        "KEEPLANE_ENROLLER_DATABASE_CA": ("keeplane-database-ca", "ca.crt"),
        "KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY": (KEYS_SECRET, "admin-key"),
        "KEEPLANE_ENROLLER_GATEWAY_RUNTIME_KEY": (KEYS_SECRET, "runtime-key"),
        # The protected runtime: its callback key and the gateway's key hashes.
        "KEEPLANE_ENROLLER_CALLBACK_KEY": (KEYS_SECRET, "callback-key"),
        "KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY_HASH": (KEYS_SECRET, "admin-key-hash"),
        "KEEPLANE_ENROLLER_GATEWAY_RUNTIME_KEY_HASH": (KEYS_SECRET, "runtime-key-hash"),
    }
    # Never optional: a missing Secret key stops the Pod instead of starting
    # an enroller without its credential.
    assert "optional" not in json.dumps(init["env"])
    plain = env_map(init)
    assert plain["KEEPLANE_ENROLLER_COPY_PREFIX"] == f"{RELEASE}-gateway-"
    assert plain["KEEPLANE_ENROLLER_STATUS_ROLES"] == ",".join(
        f"keeplane_status_{index}" for index in range(copies))
    assert plain["KEEPLANE_GATEWAY_COPY"] == {"fieldRef": {"fieldPath": "metadata.name"}}
    # The trusted base is a plain setting with no credential in it (ME-12).
    assert isinstance(plain[BASE], str)
    # The app's own password, identity Secret and the migration Secret never
    # reach the gateway Pod, and neither does the gateway database password.
    for secret in ("keeplane-app-db", "keeplane-identity", "keeplane-migration-db"):
        assert secret not in json.dumps(spec), secret
    assert "keeplane-gateway-db" not in json.dumps(init)


def test_me_05_the_app_checks_each_copy_whenever_the_enroller_runs(chart, make):
    on = app_env(chart, rendered(make(with_enroller(managed(chart)))))
    assert (CHECK, "1", False) in on
    # Asked for with the enroller, it is on; it can't be turned off while the
    # enroller runs. On its own it is refused (ME-09).
    asked = with_enroller(managed(chart))
    asked["app"]["guardStatusCheck"] = True
    assert (CHECK, "1", False) in app_env(chart, rendered(make(asked)))
    kept = with_enroller(managed(chart))
    kept["app"]["guardStatusCheck"] = False
    output = rendered(make(kept))
    assert (CHECK, "1", False) in app_env(chart, output)
    # Only the app gets the setting.
    assert output.count(CHECK) == 1


def test_me_06_the_migration_job_sets_the_roles_grants_for_every_copy(chart, make):
    job = migration(chart, rendered(make(with_enroller(managed(chart), copies=3))))
    expected = ("python /app/manage.py configure_guard_status_access --app-role keeplane_app"
                " --enroller-role keeplane_enroller"
                f" --copy {RELEASE}-gateway-0=keeplane_status_0"
                f" --copy {RELEASE}-gateway-1=keeplane_status_1"
                f" --copy {RELEASE}-gateway-2=keeplane_status_2")
    lines = [line.strip() for line in job.splitlines()]
    assert lines[lines.index("- |") + 1:lines.index("- |") + 3] == [
        "python /app/manage.py migrate --noinput", expected]
    # With CLI sign-in both steps run, migration first.
    sign_in = with_enroller(managed(chart))
    sign_in["app"]["cliSignIn"] = {"enabled": True}
    sign_in["app"]["postgres"]["publicOrigin"] = "https://unused.example.test"
    lines = [line.strip() for line in migration(chart, rendered(make(sign_in))).splitlines()]
    start = lines.index("- |") + 1
    assert lines[start:start + 3] == ["python /app/manage.py migrate --noinput",
                                      "python /app/manage.py register_cli_client",
                                      "python /app/manage.py register_cli_client --device"]
    assert lines[start + 3].startswith("python /app/manage.py configure_guard_status_access ")


def test_me_07_copy_egress_reaches_postgres_only_with_the_enroller(chart, policy, make):
    def egress(values):
        values["networkPolicy"] = {"egressEnabled": True, "egress": {
            "modelEndpoints": MODELS, "postgres": APP_DATABASE,
            "gatewayDatabase": GATEWAY_DATABASE}}
        return policy.policies(rendered(make(values)))[f"{RELEASE}-gateway-egress"]["spec"]

    to_app = {"to": [{"podSelector": {"matchLabels": {"app": f"{RELEASE}-app"}}}],
              "ports": [{"protocol": "TCP", "port": 3000}]}
    without = egress(managed(chart))["egress"]
    with_it = egress(with_enroller(managed(chart)))["egress"]
    # The enroller's database, then the app: the protected runtime's checks.
    assert with_it == without + policy.destination_rules(APP_DATABASE) + [to_app]
    assert policy.destination_rules(APP_DATABASE)[0] not in without
    assert to_app not in without

    def ingress(values):
        values["networkPolicy"] = {"appIngressEnabled": True, "publicEntry": {
            "namespaceSelector": {"kubernetes.io/metadata.name": "ingress-nginx"}}}
        return policy.policies(rendered(make(values)))[f"{RELEASE}-app-ingress"]["spec"]

    from_copies = {"from": [{"podSelector": {"matchLabels": {
        "app.kubernetes.io/name": "agentgateway-standalone",
        "app.kubernetes.io/instance": RELEASE}}}],
        "ports": [{"protocol": "TCP", "port": 3000}]}
    before = ingress(managed(chart))["ingress"]
    after = ingress(with_enroller(managed(chart)))["ingress"]
    assert after == before + [from_copies]
    assert len(before) == 1


def test_me_08_the_enroller_adds_only_the_protected_service_and_the_apps_pull_secret(
        chart, make):
    values = managed(chart)
    values["app"]["imagePullSecrets"] = [{"name": "keeplane-registry"}]
    before = rendered(make(values))
    after = rendered(make(with_enroller(values)))
    # The only new object is the protected port's Service (PA-02); no new kind.
    assert sorted(kinds(chart, before) + [("Service", f"{RELEASE}-gateway-runtime")]) \
        == kinds(chart, after)
    copies = next(doc for doc in chart.of_kind(after, "StatefulSet")
                  if chart.name_of(doc) == f"{RELEASE}-gateway")
    assert "- name: keeplane-registry" in copies
    assert "keeplane-registry" not in next(
        doc for doc in chart.of_kind(before, "StatefulSet")
        if chart.name_of(doc) == f"{RELEASE}-gateway")


def refusal_cases(chart):
    base = managed(chart)
    existing = chart.postgres_values("existing")

    def changed(values, change):
        values = copy.deepcopy(values)
        change(values)
        return values

    enroller = with_enroller(base)
    return {
        "existing-gateway": (with_enroller(existing),
                             "gateway.enroller.enabled applies only to the managed gateway"),
        "check-existing-gateway": (changed(existing, lambda v: v["app"].update(
            guardStatusCheck=True)), "app.guardStatusCheck applies only to the managed gateway"),
        "no-approvals-user": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            approvalsUser="")), "gateway.enroller.approvalsUser must name"),
        "approvals-user-case": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            approvalsUser="Keeplane_Enroller")), "gateway.enroller.approvalsUser must name"),
        "too-few-roles": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            statusRoles=["keeplane_status_0"])), "gateway.copies is 2, but 1 roles are listed"),
        "more-copies": (changed(enroller, lambda v: v["gateway"].update(copies=3)),
                        "gateway.copies is 3, but 2 roles are listed"),
        "bad-role": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            statusRoles=["keeplane_status_0", "status-1"])), "gateway.enroller.statusRoles[1]"),
        "shared-role": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            statusRoles=["keeplane_status_0", "keeplane_status_0"])),
            "gateway.enroller needs its own roles"),
        "app-role": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            approvalsUser="keeplane_app")), "gateway.enroller needs its own roles"),
        "migration-role": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            statusRoles=["keeplane_status_0", "keeplane_migrate"])),
            "gateway.enroller needs its own roles"),
        "no-approvals-secret": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            approvalsSecret="")), "gateway.enroller.approvalsSecret is required"),
        "no-status-secret": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            statusSecret="")), "gateway.enroller.statusSecret is required"),
        "app-secret": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            approvalsSecret="keeplane-app-db")), "must be Secrets of their own"),
        "keys-secret": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            statusSecret="keeplane-gateway-keys")), "must be Secrets of their own"),
        # null removes a default, as an installer would have to.
        "no-limits": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            resources={"requests": {"cpu": "25m"}, "limits": None})),
            "gateway.enroller.resources.limits needs cpu and memory"),
        "no-memory-limit": (changed(enroller, lambda v: v["gateway"]["enroller"].update(
            resources={"limits": {"cpu": "1", "memory": None}})),
            "gateway.enroller.resources.limits needs cpu and memory"),
        "volume-name": (changed(enroller, lambda v: v["gateway"]["extraVolumes"].append(
            {"name": "keeplane-guard", "emptyDir": {}})), "uses the name keeplane-guard"),
        "guard-path": (changed(enroller, lambda v: v["gateway"]["extraVolumeMounts"].append(
            {"name": "provider-keys", "mountPath": "/installed/"})),
            "mounts something at or under /installed"),
        "under-guard-path": (changed(enroller, lambda v: v["gateway"]["extraVolumeMounts"]
                                     .append({"name": "provider-keys",
                                              "mountPath": "/installed/keys"})),
                             "mounts something at or under /installed"),
        "gateway-user": (changed(enroller, lambda v: v["agentgateway-standalone"].update(
            securityContext={"runAsUser": 1000})),
            "agentgateway-standalone.securityContext.runAsUser is 1000"),
        "gateway-pod-user": (changed(enroller, lambda v: v["agentgateway-standalone"].update(
            podSecurityContext={"runAsUser": 0})),
            "agentgateway-standalone.podSecurityContext.runAsUser is 0"),
        "check-alone": (changed(base, lambda v: v["app"].update(guardStatusCheck=True)),
                        "app.guardStatusCheck can be on only together with the model enroller"),
        # The protected runtime needs the shared gateway database and keeps
        # the admin address on loopback.
        "readonly-gateway": (changed(enroller, lambda v: v["agentgateway-standalone"].update(
            mode="readonly", database={"postgres": {"url": ""}})),
            "gateway.enroller needs agentgateway-standalone.mode=database"),
        "admin-address": (changed(enroller, lambda v: v["agentgateway-standalone"]["config"]
                                  .update(config={"adminAddr": "0.0.0.0:15000"})),
                          "agentgateway-standalone.config.config.adminAddr is 0.0.0.0:15000"),
    }


def test_me_09_unsafe_or_incomplete_settings_are_refused(chart, make):
    for label, (values, message) in refusal_cases(chart).items():
        result = make(values)
        assert result.returncode != 0, label
        assert message in result.stderr, (label, result.stderr)
    # Without PostgreSQL there is no guard-status table: the local trial is refused.
    for args, message in (
        (("--set", "gateway.enroller.enabled=true"), "gateway.enroller needs app.postgres"),
        (("--set", "app.guardStatusCheck=true"),
         "app.guardStatusCheck can be on only together with the model enroller"),
    ):
        refused(make(None, "-f", "deploy/local/values.yaml", *args), message)
    # The gateway may say it runs as 65532, the guard folder's owner.
    same_user = with_enroller(managed(chart))
    same_user["agentgateway-standalone"]["securityContext"] = {"runAsUser": 65532}
    rendered(make(same_user))
    # ...and may name the loopback admin address the protected runtime uses.
    loopback = with_enroller(managed(chart))
    loopback["agentgateway-standalone"]["config"]["config"] = {"adminAddr": "127.0.0.1:15000"}
    rendered(make(loopback))
    # Pod names longer than 63 characters can't name a copy: the longest
    # release name Helm takes (53) fits up to copy 9, not copy 31.
    refused(make(with_enroller(managed(chart), copies=32), release="r" * 53),
            "r" * 53 + "-gateway-31", "must be at most 63 characters")
    rendered(make(with_enroller(managed(chart), copies=10), release="r" * 53))
    # The values schema refuses unknown keys and other types.
    for change in ({"approvalsPassword": "x"}, {"statusRoles": "keeplane_status_0"},
                   {"enabled": "yes"}):
        values = with_enroller(managed(chart))
        values["gateway"]["enroller"].update(change)
        assert make(values).returncode != 0, change
    text = managed(chart)
    text["app"]["guardStatusCheck"] = "true"
    assert make(text).returncode != 0


def test_me_10_values_and_guides_describe_the_settings():
    values = VALUES.read_text()
    block = values[values.index("  enroller:\n"):]
    assert re.search(r"^    enabled: false$", block, re.M)
    assert re.search(r"^  guardStatusCheck: false$", values, re.M)
    for name in ("approvalsUser", "approvalsSecret", "statusRoles", "statusSecret",
                 "copy-0-password", "resources"):
        assert name in block, name
    reference = REFERENCE.read_text()
    section = reference.split("\n## Model enroller\n", 1)[1].split("\n## ", 1)[0]
    for phrase in ("gateway.enroller.enabled", "approvalsUser", "approvalsSecret",
                   "statusRoles", "statusSecret", "copy-0-password", "app.guardStatusCheck",
                   "KEEPLANE_GUARD_STATUS_CHECK", "configure_guard_status_access",
                   "gateway.mode=existing", "secretKeyRef", "no port",
                   "networkPolicy.egress.postgres", "restart", "Helm refuses",
                   "protected runtime", "65532", "callback-key", "/installed/gateway.json",
                   "agentgateway-standalone.mode=database", "5000",
                   # The literal-password and base-size refusals (ME-14, ME-15).
                   "agentgateway-standalone.database.postgres.url",
                   "${KEEPLANE_DB_PASSWORD}", "gateway-database-secret.md",
                   "KEEPLANE_ENROLLER_RUNTIME_BASE", "120 KiB", "122880"):
        assert phrase in section, phrase
    assert "can't be turned on yet" not in reference
    assert "Helm refuses the enroller for now" not in reference
    assert "kubernetes-installation-reference.md#model-enroller" in ROLES_GUIDE.read_text()
    assert "gateway.enroller" in ARCHITECTURE.read_text()


def test_me_11_the_enroller_and_its_check_can_be_turned_on(chart, make):
    # The temporary refusal is gone: the shipped chart installs the protected
    # runtime, so the enroller and the per-copy check turn on together.
    assert not (ROOT / chart.CHART / NOT_YET).exists()
    output = rendered(make(with_enroller(managed(chart))))
    assert "can't be turned on yet" not in output
    assert (CHECK, "1", False) in app_env(chart, output)
    # Every refusal that still applies stays (ME-09): a customer-run gateway,
    # the check on its own, and no PostgreSQL.
    refused(make(with_enroller(chart.postgres_values("existing"))),
            "gateway.enroller.enabled applies only to the managed gateway")
    alone = managed(chart)
    alone["app"]["guardStatusCheck"] = True
    refused(make(alone),
            "app.guardStatusCheck can be on only together with the model enroller")
    refused(make(None, "-f", "deploy/local/values.yaml",
                 "--set", "gateway.enroller.enabled=true"),
            "gateway.enroller needs app.postgres")


def runtime_base(chart, policy, output):
    init = named(pod(copies_of(chart, policy, output))["initContainers"],
                 "prepare-model-enroller")
    return env_map(init)[BASE], init


def test_me_12_each_copy_starts_from_the_charts_own_gateway_configuration(
        chart, policy, make, tmp_path):
    values = with_enroller(managed(chart))
    text, init = runtime_base(chart, policy, rendered(make(values)))
    base = json.loads(text)
    # The bundled chart's rendered configuration: the database storage and
    # address it adds, the chart's two strict key policies, the installer's
    # models, and the admin address pinned to loopback.
    assert base["config"] == {"adminAddr": "127.0.0.1:15000", "storage": {"mode": "hybrid"},
                              "database": {"url": GATEWAY_DATABASE_URL}}
    assert base["gateways"] == {"default": {"port": 4000}}
    assert base["ui"]["policies"]["apiKey"] == {
        "mode": "strict", "keys": [{"keyHash": "${GATEWAY_ADMIN_KEY_HASH}"}]}
    assert base["llm"]["policies"]["apiKey"] == {
        "mode": "strict", "keys": [{"keyHash": "${GATEWAY_RUNTIME_KEY_HASH}"}]}
    assert [model["name"] for model in base["llm"]["models"]] == [chart.UNRELATED_MODEL]
    # The init step writes out only the key hashes: the gateway database
    # password stays a variable the gateway reads from its own environment.
    hashes = {name: "sha256:" + hashlib.sha256(name.encode()).hexdigest()
              for name in ("GATEWAY_ADMIN_KEY_HASH", "GATEWAY_RUNTIME_KEY_HASH")}
    environ = {"KEEPLANE_ENROLLER_CALLBACK_KEY": "c" * 64, BASE: text,
               **{f"KEEPLANE_ENROLLER_{name}": value for name, value in hashes.items()}}
    files = runtime_plan(environ)
    assert list(files) == ["manifest.json", "callback-key", "trusted.json", "gateway.json"]
    assert files["trusted.json"] == files["gateway.json"]
    trusted = json.loads(files["trusted.json"])
    assert trusted["ui"]["policies"]["apiKey"]["keys"] == [
        {"keyHash": hashes["GATEWAY_ADMIN_KEY_HASH"]}]
    assert trusted["llm"]["policies"]["apiKey"]["keys"] == [
        {"keyHash": hashes["GATEWAY_RUNTIME_KEY_HASH"]}]
    assert trusted["config"]["database"]["url"] == GATEWAY_DATABASE_URL
    assert json.loads(files["manifest.json"]) == {"version": 2, "enabled": False}
    guard = tmp_path / "installed"
    install_runtime(files, guard)
    assert sorted(path.name for path in guard.iterdir()) == sorted(files)
    # A key rotation's next hashes reach the init step only while the gateway
    # reads them too, from the same Secret keys.
    rotation = with_enroller(managed(chart))
    gateway = rotation["agentgateway-standalone"]
    gateway["extraEnv"] += [
        chart.secret_env("GATEWAY_RUNTIME_KEY_HASH_NEXT", KEYS_SECRET, "runtime-key-hash-next"),
        chart.secret_env("GATEWAY_ADMIN_KEY_HASH_NEXT", KEYS_SECRET, "admin-key-hash-next")]
    gateway["config"]["ui"] = {"policies": {"apiKey": {"mode": "strict", "keys": [
        {"keyHash": "${GATEWAY_ADMIN_KEY_HASH}"}, {"keyHash": "${GATEWAY_ADMIN_KEY_HASH_NEXT}"}]}}}
    gateway["config"]["llm"]["policies"] = {"apiKey": {"mode": "strict", "keys": [
        {"keyHash": "${GATEWAY_RUNTIME_KEY_HASH}"},
        {"keyHash": "${GATEWAY_RUNTIME_KEY_HASH_NEXT}"}]}}
    text, rotating = runtime_base(chart, policy, rendered(make(rotation)))
    references = {entry["name"]: entry["valueFrom"]["secretKeyRef"]["key"]
                  for entry in rotating["env"] if "secretKeyRef" in entry.get("valueFrom", {})}
    assert references["KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY_HASH_NEXT"] == "admin-key-hash-next"
    assert references["KEEPLANE_ENROLLER_GATEWAY_RUNTIME_KEY_HASH_NEXT"] == \
        "runtime-key-hash-next"
    assert "KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY_HASH_NEXT" not in json.dumps(init)
    # Without the next hashes the init step stops rather than start a copy
    # whose policy names a hash it doesn't have.
    with pytest.raises(Unprepared, match="names a key hash this copy was not given"):
        runtime_plan({**environ, BASE: text})
    # The base is part of the Pod template: a change the bundled chart would
    # reload in place (a model) now restarts the copies from the new base.
    moved = with_enroller(managed(chart))
    moved["agentgateway-standalone"]["config"]["llm"]["models"][0]["params"]["model"] = "other"
    assert runtime_base(chart, policy, rendered(make(moved)))[0] != runtime_base(
        chart, policy, rendered(make(values)))[0]


def test_me_13_the_app_reads_the_callback_key_from_the_gateway_keys(chart, make):
    output = rendered(make(with_enroller(managed(chart))))
    variables = app_env(chart, output)
    assert ("RUNTIME_AUTHORIZER_KEY_FILE", "/run/gateway-keys/callback-key", False) \
        in variables
    # The app reads no guard file: the per-copy check reads the guard-status rows.
    names = {name for name, _, _ in variables}
    assert "RUNTIME_GUARD_MANIFEST_FILE" not in names
    # Off without the enroller.
    assert "RUNTIME_AUTHORIZER_KEY_FILE" not in rendered(make(managed(chart)))


LITERAL_PASSWORD = "literal-gateway-db-password"
DATABASE_HOST = "@gateway-db.database.svc.cluster.local:5432/keeplane"


def with_gateway_url(values, url):
    values = copy.deepcopy(values)
    values["agentgateway-standalone"]["database"]["postgres"]["url"] = url
    return values


def test_me_14_a_literal_gateway_database_password_is_refused_with_the_enroller(
        chart, policy, make):
    literal = (
        f"postgresql://keeplane:{LITERAL_PASSWORD}{DATABASE_HOST}",
        f"postgres://keeplane:{LITERAL_PASSWORD}{DATABASE_HOST}",
        # A variable with literal text beside it is still a literal password.
        f"postgresql://keeplane:${{KEEPLANE_DB_PASSWORD}}{LITERAL_PASSWORD}{DATABASE_HOST}",
        f"postgresql://keeplane{DATABASE_HOST}?sslmode=verify-full&password={LITERAL_PASSWORD}",
        f"postgresql://keeplane:${{KEEPLANE_DB_PASSWORD}}{DATABASE_HOST}"
        f"?sslpassword={LITERAL_PASSWORD}",
    )
    for url in literal:
        result = make(with_gateway_url(with_enroller(managed(chart)), url))
        refused(result, "gateway.enroller needs the gateway database password",
                "agentgateway-standalone.database.postgres.url",
                "postgresql://keeplane:${KEEPLANE_DB_PASSWORD}@",
                "docs/guide/gateway-database-secret.md")
        # The refusal never repeats the password.
        assert LITERAL_PASSWORD not in result.stderr, url
    # The variable form the guides show, a GATEWAY_* variable and a URL with
    # no password render, and the base carries the URL as written.
    for url in (GATEWAY_DATABASE_URL,
                f"postgresql://keeplane:${{GATEWAY_DB_PASSWORD}}{DATABASE_HOST}",
                f"postgresql://keeplane{DATABASE_HOST}?sslmode=verify-full",
                f"postgresql://keeplane:${{KEEPLANE_DB_PASSWORD}}{DATABASE_HOST}"
                "?sslmode=verify-full&sslpassword=${KEEPLANE_DB_KEY_PASSWORD}"):
        output = rendered(make(with_gateway_url(with_enroller(managed(chart)), url)))
        text, _ = runtime_base(chart, policy, output)
        assert json.loads(text)["config"]["database"]["url"] == url
    # Without the enroller the chart renders the URL as before.
    rendered(make(with_gateway_url(managed(chart), literal[0])))


def with_models(values, count):
    """values whose gateway configuration lists count copies of the installer's model."""
    values = copy.deepcopy(values)
    models = values["agentgateway-standalone"]["config"]["llm"]["models"]
    model = models[0]
    models[:] = [{**copy.deepcopy(model), "name": f"model-{index:04d}"}
                 for index in range(count)]
    return values


def test_me_15_a_base_too_large_for_one_environment_value_is_refused(chart, policy, make):
    # Linux refuses one environment value over 128 KiB; the chart stops at
    # 120 KiB and names the cause instead of a Pod that can't start.
    large = with_models(managed(chart), 1200)
    result = make(with_enroller(large))
    refused(result, "KEEPLANE_ENROLLER_RUNTIME_BASE", "over 128 KiB",
            "over the chart's limit of 122880 bytes (120 KiB)",
            "Shorten agentgateway-standalone.config")
    size = int(re.search(r"configuration is (\d+) bytes", result.stderr).group(1))
    assert size > 122880
    # The same configuration renders without the enroller, and a smaller one
    # with it.
    rendered(make(large))
    text, _ = runtime_base(chart, policy,
                           rendered(make(with_enroller(with_models(managed(chart), 100)))))
    assert len(json.loads(text)["llm"]["models"]) == 100
    assert len(text.encode()) <= 122880
