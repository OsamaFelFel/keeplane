"""Every Secret the chart mounts into a Keeplane pod has a restrictive file mode.

Cases CM-01 to CM-03 in chart-credential-mounts-cases.md. CM-01 and CM-02
render the chart with Helm and are skipped when Helm is missing; CM-03 reads
only the installation reference and always runs.
"""

import json
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "docs/guide/kubernetes-installation-reference.md"
# The only mode the chart uses for a mounted Secret: owner and group read.
MODE = 0o440
APP_USER = 65532
# Each Keeplane pod and the Secret volumes it must mount in some installation.
EXPECTED = {
    ("Deployment", "app"): {"gateway-keys", "database-credentials", "database-ca",
                            "identity", "first-admin", "gateway-ca"},
    ("Job", "existing-gateway-preflight"): {"gateway-keys", "gateway-ca"},
    ("Job", "accounts-migrate"): {"database-credentials", "database-ca", "identity"},
}


@pytest.fixture(scope="module")
def chart():
    """Rendered chart helpers; skips without Helm, as the other chart checks do."""
    from tests.integration import test_chart_installation_shape as shape

    return shape


def installations(chart, directory):
    """Every supported installation, plus an existing-gateway one with no storage."""
    def values_file(name, values):
        path = directory / (name + ".json")
        path.write_text(json.dumps(values))
        return ("-f", str(path))

    managed = chart.postgres_values("managed")
    existing = chart.postgres_values("existing")
    existing_ca = chart.postgres_values("existing")
    existing_ca["gateway"].update(url="https://gateway.example.test",
                                  caSecret="customer-gateway-ca")
    sign_in = chart.postgres_values("managed")
    sign_in["app"]["cliSignIn"] = {"enabled": True}
    sign_in["app"]["postgres"]["publicOrigin"] = "https://unused.example.test"
    return {
        "managed-local": ("-f", "deploy/local/values.yaml"),
        "existing-local": ("-f", "deploy/local/existing-values.yaml"),
        "managed-postgres": values_file("managed", managed),
        "managed-postgres-cli-sign-in": values_file("sign-in", sign_in),
        "existing-postgres": values_file("existing", existing),
        "existing-postgres-gateway-ca": values_file("existing-ca", existing_ca),
        # Neither PostgreSQL nor the local trial: the pod still needs the group
        # that lets its user read the keys and the CA.
        "existing-keys-only": (
            "--set", "gateway.mode=existing", "--set", "gateway.install=false",
            "--set", "gateway.url=https://gateway.example.test",
            "--set", "gateway.expectedVersion=1.6.0",
            "--set", "gateway.keysSecret=keeplane-gateway-keys",
            "--set", "gateway.caSecret=customer-gateway-ca",
        ),
    }


@pytest.fixture(scope="module")
def rendered(chart, tmp_path_factory):
    directory = tmp_path_factory.mktemp("credential-mounts")
    outputs = {}
    for label, args in installations(chart, directory).items():
        result = chart.run("template", "keeplane", chart.CHART, "--namespace", "keeplane",
                           *args)
        assert result.returncode == 0, (label, result.stderr)
        outputs[label] = result.stdout
    return outputs


def pod_spec(chart, document):
    return chart.block(chart.block(document, "template"), "spec")


def secret_volumes(chart, document):
    """{volume: (defaultMode or None, per-item modes)} for every Secret volume."""
    found = {}
    for item in chart.items(chart.block(pod_spec(chart, document), "volumes")):
        assert not re.search(r"^\s+projected:", item, re.M), (
            "A projected volume needs its own mode check", item)
        if not re.search(r"^\s+secret:", item, re.M):
            continue
        mode = chart.scalar(item, "defaultMode")
        found[chart.scalar(item, "name")] = (
            int(mode, 8) if mode else None, re.findall(r"^\s+mode: (\S+)", item, re.M))
    return found


def pod_containers(chart, document):
    return [*chart.containers(document, "initContainers"), *chart.containers(document)]


def can_read(mode, user, fs_group):
    """Secret files are owned by root, with group fsGroup when the pod sets one."""
    if mode & 0o004 or (user == 0 and mode & 0o400):
        return True
    return fs_group is not None and bool(mode & 0o040)


def short_name(document, chart):
    return chart.name_of(document).removeprefix("keeplane-")


def test_cm_01_every_secret_volume_has_an_explicit_owner_and_group_read_mode(chart, rendered):
    seen, problems = {}, []
    for label, output in rendered.items():
        for document in chart.workloads(output):
            key = (chart.kind_of(document), short_name(document, chart))
            for volume, (mode, item_modes) in secret_volumes(chart, document).items():
                seen.setdefault(key, set()).add(volume)
                where = f"{label}: {key[0]} {chart.name_of(document)} volume {volume}"
                if mode is None:
                    problems.append(where + " has no defaultMode (Kubernetes uses 0644)")
                elif mode != MODE:
                    problems.append(f"{where} has mode {oct(mode)}, expected {oct(MODE)}")
                if item_modes:
                    problems.append(f"{where} overrides the mode per file: {item_modes}")
    print(json.dumps({f"{kind} {name}": sorted(volumes)
                      for (kind, name), volumes in sorted(seen.items())}, indent=2))
    assert not problems, problems
    # Only Keeplane's own pods mount Secrets, and each mounts the expected ones
    # somewhere: the gateway copies read their hashes with secretKeyRef only.
    assert seen == EXPECTED, seen


def test_cm_02_each_secret_is_read_only_and_readable_only_by_the_pod_user(chart, rendered):
    checked = {}
    for label, output in rendered.items():
        for document in chart.workloads(output):
            volumes = secret_volumes(chart, document)
            if not volumes:
                continue
            fs_group = chart.scalar("\n".join(pod_spec(chart, document)), "fsGroup")
            name = f"{label}: {chart.kind_of(document)} {chart.name_of(document)}"
            assert fs_group == str(APP_USER), (name, "needs fsGroup", fs_group)
            for container in pod_containers(chart, document):
                user = chart.scalar(container, "runAsUser")
                for volume, _, read_only in chart.mounts(container):
                    if volume not in volumes:
                        continue
                    mode = volumes[volume][0]
                    where = (name, chart.scalar(container, "name"), volume)
                    assert read_only, (where, "must be mounted readOnly")
                    assert user == str(APP_USER), (where, "must read as the app user", user)
                    assert can_read(mode, int(user), fs_group), (where, oct(mode))
                    # Root owns the files: other users can't read them, and
                    # nobody can change them.
                    assert not mode & 0o237, (where, oct(mode))
                    checked[where] = oct(mode)
    print(json.dumps({" / ".join(key): mode for key, mode in sorted(checked.items())},
                     indent=2))
    keys = {where[0].split(": ", 1)[1] for where in checked if where[2] == "gateway-keys"}
    assert keys == {"Deployment keeplane-app",
                    "Job keeplane-existing-gateway-preflight"}, keys


def test_cm_03_installation_reference_states_the_mode_of_every_mounted_secret():
    text = REFERENCE.read_text()
    section = text.split("## Secrets", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines()
            if line.startswith("| `") and "Read-only" in line]
    assert len(rows) >= 7, rows
    for row in rows:
        assert "mode 0440" in row, row
    assert "mode 0440" in section and "`fsGroup`" in section


def octal_mode(text):
    """A mode as Helm prints it: 0440 from Keeplane's templates, 288 from toYaml."""
    return int(text, 8) if text.startswith("0") and len(text) > 1 else int(text)


GATEWAY_GROUP = 65532
# Secret volumes an installer adds to the managed gateway copies, without a mode.
UNSET_VOLUMES = [
    {"name": "provider-ca", "secret": {"secretName": "provider-ca"}},
    {"name": "provider-token", "secret": {
        "secretName": "provider-token", "items": [{"key": "token", "path": "token"}]}},
    {"name": "provider-bundle", "projected": {"sources": [
        {"secret": {"name": "provider-client"}},
        {"configMap": {"name": "provider-ca-bundle"}},
    ]}},
]
# The same kinds of volume with explicit modes no looser than 0440.
STRICT_VOLUMES = [
    {"name": "provider-ca", "secret": {"secretName": "provider-ca", "defaultMode": 0o400}},
    {"name": "provider-token", "secret": {
        "secretName": "provider-token", "defaultMode": 0o440,
        "items": [{"key": "token", "path": "token", "mode": 0o400}]}},
    {"name": "provider-bundle", "projected": {"defaultMode": 0o040, "sources": [
        {"secret": {"name": "provider-client",
                    "items": [{"key": "tls.key", "path": "tls.key", "mode": 0o400}]}},
    ]}},
]
# Volume name -> (defaultMode, item modes) expected on the copies for each set.
UNSET_EXPECTED = {"provider-ca": (MODE, []), "provider-token": (MODE, []),
                  "provider-bundle": (MODE, [])}
STRICT_EXPECTED = {"provider-ca": (0o400, []), "provider-token": (0o440, [0o400]),
                   "provider-bundle": (0o040, [0o400])}


def gateway_secret_values(install, volumes, fs_group=GATEWAY_GROUP):
    """Values whose gateway settings mount the given Secret volumes.

    "minimal" is a managed install with neither PostgreSQL nor the local trial,
    the only kind whose gateway may set fsGroup: with either of them the
    gateway shares the provider-key volume and Helm refuses a gateway fsGroup.
    "postgres" and "existing" are the PostgreSQL installs with each gateway mode.
    """
    from tests.integration import test_chart_installation_shape as shape

    if install == "minimal":
        values = {"gateway": {"mode": "managed", "install": True,
                              "keysSecret": "keeplane-gateway-keys"},
                  "agentgateway-standalone": shape.gateway_values()}
    else:
        values = shape.postgres_values("existing" if install == "existing" else "managed")
    gateway = values["agentgateway-standalone"]
    gateway["podSecurityContext"] = {"fsGroup": fs_group}
    gateway["extraVolumes"] = [dict(volume) for volume in volumes]
    gateway["extraVolumeMounts"] = [
        {"name": volume["name"], "mountPath": "/run/" + volume["name"], "readOnly": True}
        for volume in volumes]
    return values


def render_values(chart, tmp_path, name, values):
    path = tmp_path / (name + ".json")
    path.write_text(json.dumps(values))
    return chart.run("template", "keeplane", chart.CHART, "--namespace", "keeplane",
                     "-f", str(path))


def gateway_copies(chart, output):
    return [document for document in chart.of_kind(output, "StatefulSet")
            if chart.name_of(document) == "keeplane-gateway"]


def copies_volumes(chart, output):
    """{volume: (kind, defaultMode, item modes)} on the gateway copies' StatefulSet."""
    [copies] = gateway_copies(chart, output)
    found = {}
    for item in chart.items(chart.block(pod_spec(chart, copies), "volumes")):
        kind = re.search(r"^\s+(secret|projected|persistentVolumeClaim|configMap|emptyDir):",
                         item, re.M)
        mode = chart.scalar(item, "defaultMode")
        found[chart.scalar(item, "name")] = (
            kind.group(1) if kind else None, octal_mode(mode) if mode else None,
            [octal_mode(value) for value in re.findall(r"^\s+mode: (\S+)", item, re.M)])
    return copies, found


def test_cm_04_gateway_secret_volumes_without_a_mode_get_0440(chart, tmp_path):
    observed = {}
    result = render_values(chart, tmp_path, "unset",
                           gateway_secret_values("minimal", UNSET_VOLUMES))
    assert result.returncode == 0, result.stderr
    copies, volumes = copies_volumes(chart, result.stdout)
    for name, (mode, item_modes) in UNSET_EXPECTED.items():
        assert volumes[name][1:] == (mode, item_modes), (name, volumes[name])
    assert chart.scalar("\n".join(pod_spec(chart, copies)), "fsGroup") == str(GATEWAY_GROUP)
    # Volumes that hold no Secret are left as the installer wrote them.
    assert volumes["config"] == ("configMap", None, [])
    assert volumes["tmp"] == ("emptyDir", None, [])
    observed["managed"] = {name: oct(value[1]) for name, value in volumes.items() if value[1]}
    # The bundled chart's own Deployment also lists them, but runs no pods.
    for document in chart.of_kind(result.stdout, "Deployment"):
        if "provider-ca" in "\n".join(pod_spec(chart, document)):
            assert chart.scalar(document, "replicas") == "0", chart.name_of(document)
    # The local trial's gateway mounts the shared provider-key volume without
    # fsGroup and is rendered unchanged.
    local = chart.run("template", "keeplane", chart.CHART, "--namespace", "keeplane",
                      "-f", "deploy/local/values.yaml")
    assert local.returncode == 0, local.stderr
    _, local_volumes = copies_volumes(chart, local.stdout)
    assert local_volumes["provider-keys"] == ("persistentVolumeClaim", None, []), local_volumes
    observed["managed-local"] = sorted(local_volumes)
    # With an existing gateway the chart runs no gateway, so no pod mounts them.
    existing = render_values(chart, tmp_path, "existing",
                             gateway_secret_values("existing", UNSET_VOLUMES))
    assert existing.returncode == 0, existing.stderr
    assert not gateway_copies(chart, existing.stdout)
    for document in chart.workloads(existing.stdout):
        assert not set(UNSET_EXPECTED) & set(secret_volumes(chart, document)), \
            chart.name_of(document)
    print(json.dumps(observed, indent=2))


def test_cm_05_gateway_secret_volumes_keep_a_stricter_mode(chart, tmp_path):
    result = render_values(chart, tmp_path, "strict",
                           gateway_secret_values("minimal", STRICT_VOLUMES))
    assert result.returncode == 0, result.stderr
    _, volumes = copies_volumes(chart, result.stdout)
    for name, expected in STRICT_EXPECTED.items():
        assert volumes[name][1:] == expected, (name, volumes[name])
    print(json.dumps({name: [oct(volumes[name][1]), [oct(m) for m in volumes[name][2]]]
                      for name in STRICT_EXPECTED}, indent=2))


def refused_volumes():
    """Gateway Secret volumes Helm must refuse: (volumes, message, fsGroup, install)."""
    looser = "accept only owner and group read (0440) or stricter"
    secret = lambda **fields: [{"name": "provider-ca",
                                "secret": {"secretName": "provider-ca", **fields}}]
    return {
        "default-0644": (secret(defaultMode=0o644), looser, GATEWAY_GROUP, "minimal"),
        "everyone-reads-0444": (secret(defaultMode=0o444), looser, GATEWAY_GROUP, "minimal"),
        "owner-writes-0640": (secret(defaultMode=0o640), looser, GATEWAY_GROUP, "minimal"),
        "group-writes-0460": (secret(defaultMode=0o460), looser, GATEWAY_GROUP, "minimal"),
        "executable-0550": (secret(defaultMode=0o550), looser, GATEWAY_GROUP, "minimal"),
        "setuid-04440": (secret(defaultMode=0o4440), looser, GATEWAY_GROUP, "minimal"),
        "item-0644": (secret(items=[{"key": "ca.crt", "path": "ca.crt", "mode": 0o644}]),
                      looser, GATEWAY_GROUP, "minimal"),
        "projected-0644": ([{"name": "provider-bundle", "projected": {
            "defaultMode": 0o644, "sources": [{"secret": {"name": "provider-client"}}]}}],
            looser, GATEWAY_GROUP, "minimal"),
        "projected-item-0604": ([{"name": "provider-bundle", "projected": {"sources": [
            {"secret": {"name": "provider-client", "items": [
                {"key": "tls.key", "path": "tls.key", "mode": 0o604}]}}]}}],
            looser, GATEWAY_GROUP, "minimal"),
        "mode-as-text": (secret(defaultMode="0440"), "is not a number", GATEWAY_GROUP, "minimal"),
        "no-fs-group": (secret(), "podSecurityContext.fsGroup is unset", None, "minimal"),
        "no-fs-group-strict": (secret(defaultMode=0o440),
                               "podSecurityContext.fsGroup is unset", None, "minimal"),
        "no-fs-group-projected": ([{"name": "provider-bundle", "projected": {
            "sources": [{"secret": {"name": "provider-client"}}]}}],
            "podSecurityContext.fsGroup is unset", None, "minimal"),
        # PostgreSQL (and the local trial) share the provider-key volume with
        # the gateway: Helm refuses its fsGroup, and without one any Secret volume.
        "postgres-fs-group": (secret(), "Leave the managed gateway fsGroup unset",
                              GATEWAY_GROUP, "postgres"),
        "postgres-no-fs-group": (secret(), "podSecurityContext.fsGroup is unset", None,
                                 "postgres"),
    }


def test_cm_06_gateway_secret_volumes_with_a_looser_mode_are_refused(chart, tmp_path):
    observed = {}
    for label, (volumes, message, fs_group, install) in refused_volumes().items():
        result = render_values(chart, tmp_path, label,
                               gateway_secret_values(install, volumes, fs_group))
        assert result.returncode != 0, label
        assert message in result.stderr, (label, result.stderr)
        if label != "postgres-fs-group":
            assert "agentgateway-standalone.extraVolumes[0]" in result.stderr, (label,
                                                                             result.stderr)
        observed[label] = result.stderr.strip().splitlines()[-1][-160:]
    # A looser mode is ignored with an existing gateway: no pod mounts it.
    existing = render_values(chart, tmp_path, "existing-loose", gateway_secret_values(
        "existing", refused_volumes()["default-0644"][0], None))
    assert existing.returncode == 0, existing.stderr
    assert not gateway_copies(chart, existing.stdout)
    print(json.dumps(observed, indent=2))


def test_cm_07_guides_state_the_gateway_secret_volume_rules():
    section = REFERENCE.read_text().split("## Secrets", 1)[1].split("\n## ", 1)[0]
    for phrase in ("agentgateway-standalone.extraVolumes", "mode 0440", "stricter",
                   "0644", "podSecurityContext.fsGroup", "provider-key volume",
                   "gateway.mode=existing", "no extra volumes for the app"):
        assert phrase in " ".join(section.split()), phrase
    guide = " ".join((ROOT / "docs/guide/gateway-configuration.md").read_text().split())
    assert "`agentgateway-standalone.extraVolumes` is mounted with mode 0440" in guide


def test_catalog_lists_exactly_these_cases():
    catalog = Path(__file__).with_name("chart-credential-mounts-cases.md").read_text()
    listed = re.findall(r"^\| (CM-\d+) \|", catalog, re.M)
    defined = sorted({name.split("_")[2] for name in globals()
                      if re.fullmatch(r"test_cm_\d+_.+", name)})
    assert listed == ["CM-" + number for number in defined], (listed, defined)
