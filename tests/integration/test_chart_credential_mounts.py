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


def test_catalog_lists_exactly_these_cases():
    catalog = Path(__file__).with_name("chart-credential-mounts-cases.md").read_text()
    listed = re.findall(r"^\| (CM-\d+) \|", catalog, re.M)
    defined = sorted({name.split("_")[2] for name in globals()
                      if re.fullmatch(r"test_cm_\d+_.+", name)})
    assert listed == ["CM-" + number for number in defined], (listed, defined)
