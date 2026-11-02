"""Render the model enroller beside each managed gateway copy (ADR 027).

Cases ME-01 to ME-11 in chart-model-enroller-cases.md. All but ME-10 render
the chart with Helm and are skipped when Helm is missing; ME-10 reads only the
values file and the guides and always runs. Helm refuses the enroller in the
shipped chart for now (ME-11); ME-02 to ME-09 render a test copy of the chart
without that one refusal (see ready_chart).
"""

import copy
import json
from pathlib import Path
import re
import shutil

import pytest

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
NOT_YET = "templates/checks/first/protected-runtime.yaml"
NOT_YET_MESSAGE = (
    "gateway.enroller can't be turned on yet: this chart doesn't install "
    "Keeplane's protected runtime on the managed gateway")


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


@pytest.fixture(scope="module")
def ready_chart(chart, tmp_path_factory):
    """A test copy of the chart without its one "not yet" refusal.

    Helm refuses gateway.enroller until the chart installs the protected
    runtime (templates/checks/first/protected-runtime.yaml). To render the
    enroller's real templates without a supported or hidden values key, the
    cases render a copy of the chart that lacks only that file. ME-11 checks
    the shipped chart refuses, and that the copy differs by that file alone.
    """
    shipped = ROOT / chart.CHART
    copy_dir = tmp_path_factory.mktemp("enroller-chart") / "keeplane"
    shutil.copytree(shipped, copy_dir)
    (copy_dir / NOT_YET).unlink()
    return copy_dir


def chart_files(directory):
    return {str(path.relative_to(directory)) for path in directory.rglob("*")
            if path.is_file()}


@pytest.fixture
def make(chart, ready_chart, tmp_path):
    def build(values=None, *args, release=RELEASE, shipped=False):
        files = []
        if values is not None:
            path = tmp_path / f"values-{len(list(tmp_path.iterdir()))}.json"
            path.write_text(json.dumps(values))
            files = ["-f", str(path)]
        target = chart.CHART if shipped else str(ready_chart)
        return chart.run("template", release, target, "--namespace", "keeplane",
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
        output = rendered(make(*args, shipped=True))
        for absent in (CHECK, "model-enroller", "keeplane-guard", "KEEPLANE_ENROLLER_",
                       "configure_guard_status_access", "/installed"):
            assert absent not in output, (label, absent)
        # The test copy renders exactly the same with the enroller off.
        assert rendered(make(*args)) == output, label


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
    # Same settings, image and security: no database credential or key file.
    assert {key: value for key, value in gateway_after.items() if key != "volumeMounts"} \
        == {key: value for key, value in gateway_before.items() if key != "volumeMounts"}
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
        "KEEPLANE_ENROLLER_GATEWAY_ADMIN_KEY": ("keeplane-gateway-keys", "admin-key"),
        "KEEPLANE_ENROLLER_GATEWAY_RUNTIME_KEY": ("keeplane-gateway-keys", "runtime-key"),
    }
    # Never optional: a missing Secret key stops the Pod instead of starting
    # an enroller without its credential.
    assert "optional" not in json.dumps(init["env"])
    plain = env_map(init)
    assert plain["KEEPLANE_ENROLLER_COPY_PREFIX"] == f"{RELEASE}-gateway-"
    assert plain["KEEPLANE_ENROLLER_STATUS_ROLES"] == ",".join(
        f"keeplane_status_{index}" for index in range(copies))
    assert plain["KEEPLANE_GATEWAY_COPY"] == {"fieldRef": {"fieldPath": "metadata.name"}}
    # The app's own password, identity Secret and the migration Secret never
    # reach the gateway Pod.
    for secret in ("keeplane-app-db", "keeplane-identity", "keeplane-migration-db"):
        assert secret not in json.dumps(spec), secret


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

    without = egress(managed(chart))["egress"]
    with_it = egress(with_enroller(managed(chart)))["egress"]
    assert with_it == without + policy.destination_rules(APP_DATABASE)
    assert policy.destination_rules(APP_DATABASE)[0] not in without


def test_me_08_the_enroller_adds_no_kind_and_brings_the_apps_pull_secret(chart, make):
    values = managed(chart)
    values["app"]["imagePullSecrets"] = [{"name": "keeplane-registry"}]
    before = rendered(make(values))
    after = rendered(make(with_enroller(values)))
    assert kinds(chart, before) == kinds(chart, after)
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
                   "protected runtime", "65532"):
        assert phrase in section, phrase
    assert "kubernetes-installation-reference.md#model-enroller" in ROLES_GUIDE.read_text()
    assert "gateway.enroller" in ARCHITECTURE.read_text()


def test_me_11_the_shipped_chart_refuses_the_enroller_for_now(chart, ready_chart, make):
    # The test copy lacks exactly one file of the shipped chart.
    assert chart_files(ROOT / chart.CHART) - chart_files(ready_chart) == {NOT_YET}
    assert chart_files(ready_chart) <= chart_files(ROOT / chart.CHART)
    for label, args in {
        "postgres-managed": (with_enroller(managed(chart)),),
        "postgres-existing": (with_enroller(chart.postgres_values("existing")),),
        "local-managed": (None, "-f", "deploy/local/values.yaml",
                          "--set", "gateway.enroller.enabled=true"),
    }.items():
        result = make(*args, shipped=True)
        assert result.returncode != 0, label
        assert NOT_YET_MESSAGE in result.stderr, (label, result.stderr)
    # With the enroller refused, the check can't be on either.
    alone = managed(chart)
    alone["app"]["guardStatusCheck"] = True
    refused(make(alone, shipped=True),
            "app.guardStatusCheck can be on only together with the model enroller")
