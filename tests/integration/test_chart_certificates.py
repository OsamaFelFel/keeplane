"""Render the chart and check how certificates reach Keeplane and the ingress.

Cases CO-H1 to CO-H5 in chart-certificates-cases.md. Rendering proves what
the chart asks Kubernetes to create, not that a certificate is valid or that a
cluster serves it.
"""

import json

import pytest


@pytest.fixture(scope="module")
def chart():
    """Rendered chart helpers; skips without Helm, as the other chart checks do."""
    from tests.integration import test_chart_installation_shape as shape

    return shape


def render(chart, tmp_path, values):
    path = tmp_path / f"values-{len(list(tmp_path.iterdir()))}.json"
    path.write_text(json.dumps(values))
    return chart.run("template", "keeplane", chart.CHART, "--namespace", "keeplane",
                     "-f", str(path))


def rendered(result):
    assert result.returncode == 0, result.stderr
    return result.stdout


def workload(chart, output, kind, name):
    return next(doc for doc in chart.of_kind(output, kind) if chart.name_of(doc) == name)


def existing_with_ca(chart, url="https://gateway.example.test"):
    values = chart.postgres_values("existing")
    values["gateway"].update(url=url, caSecret="customer-gateway-ca")
    return values


def test_co_h1_gateway_ca_reaches_the_app_and_preflight_as_a_refreshing_file(chart, tmp_path):
    output = rendered(render(chart, tmp_path, existing_with_ca(chart)))
    for kind, name, container_name in (
        ("Deployment", "keeplane-app", "app"),
        ("Job", "keeplane-existing-gateway-preflight", "preflight"),
    ):
        document = workload(chart, output, kind, name)
        container = next(item for item in chart.containers(document)
                         if chart.scalar(item, "name") == container_name)
        assert ("KEEPLANE_GATEWAY_CA_FILE", "/run/keeplane-gateway-ca/ca.crt", False) in \
            chart.env(container)
        mounted = {volume: (path, read_only)
                   for volume, path, read_only in chart.mounts(container)}
        assert mounted["gateway-ca"] == ("/run/keeplane-gateway-ca", True)
        assert chart.volumes(document)["gateway-ca"] == ("secret", "customer-gateway-ca")
        # Without subPath, Kubernetes refreshes a renewed CA in running pods.
        assert "subPath" not in document
    # The chart only references the Secret; it never renders one.
    assert not chart.of_kind(output, "Secret")


def test_co_h2_without_a_gateway_ca_nothing_changes(chart, tmp_path):
    values = chart.postgres_values("existing")
    output = rendered(render(chart, tmp_path, values))
    assert "KEEPLANE_GATEWAY_CA_FILE" not in output and "gateway-ca" not in output
    managed = rendered(render(chart, tmp_path, chart.postgres_values("managed")))
    assert "KEEPLANE_GATEWAY_CA_FILE" not in managed


def test_co_h3_gateway_ca_is_refused_for_the_managed_gateway(chart, tmp_path):
    values = chart.postgres_values("managed")
    values["gateway"]["caSecret"] = "customer-gateway-ca"
    result = render(chart, tmp_path, values)
    assert result.returncode != 0
    assert "caSecret" in result.stderr


def test_co_h4_ingress_requires_and_only_references_its_tls_secret(chart, tmp_path):
    values = chart.postgres_values("managed")
    output = rendered(render(chart, tmp_path, values))
    ingress = workload(chart, output, "Ingress", "keeplane-app")
    assert 'secretName: "keeplane-tls"' in ingress
    assert ingress.count('"keeplane.example.test"') == 2  # the TLS host and the rule host
    assert not chart.of_kind(output, "Secret")
    values["ingress"]["tlsSecretName"] = ""
    result = render(chart, tmp_path, values)
    assert result.returncode != 0
    assert "ingress.tlsSecretName is required when ingress is enabled" in result.stderr


def secret_modes(chart, document):
    """Each Secret volume's file mode; Kubernetes uses 0644 when none is given."""
    spec = chart.block(chart.block(document, "template"), "spec")
    return {chart.scalar(item, "name"): int(chart.scalar(item, "defaultMode") or "0644", 8)
            for item in chart.items(chart.block(spec, "volumes")) if "secret:" in item}


def can_read(mode, user, fs_group):
    """Secret files are owned by root, with group fsGroup when the pod sets one."""
    if mode & 0o004 or (user == 0 and mode & 0o400):
        return True
    return bool(fs_group) and bool(mode & 0o040)


def test_co_h5_every_mounted_certificate_is_readable_by_the_user_that_reads_it(chart, tmp_path):
    output = rendered(render(chart, tmp_path, existing_with_ca(chart)))
    checked = set()
    for kind, name, container_name in (
        ("Deployment", "keeplane-app", "app"),
        ("Job", "keeplane-existing-gateway-preflight", "preflight"),
        ("Job", "keeplane-accounts-migrate", "migrate"),
    ):
        document = workload(chart, output, kind, name)
        container = next((item for item in chart.containers(document)
                          if chart.scalar(item, "name") == container_name),
                         chart.containers(document)[0])
        user = int(chart.scalar(container, "runAsUser"))
        assert user != 0, f"{name} must not read certificates as root"
        fs_group = chart.scalar(document, "fsGroup")
        modes = secret_modes(chart, document)
        for volume, _, _ in chart.mounts(container):
            if volume in ("gateway-ca", "database-ca", "gateway-keys"):
                assert can_read(modes[volume], user, fs_group), (name, volume, oct(modes[volume]))
                checked.add((name, volume))
    assert ("keeplane-existing-gateway-preflight", "gateway-ca") in checked
    assert ("keeplane-app", "gateway-ca") in checked
    assert ("keeplane-accounts-migrate", "database-ca") in checked


# --- trust.extraCaBundle: CO-H6 to CO-H10 --------------------------------------------

BUNDLE = "/run/keeplane-trust/ca-bundle.pem"
EXTRA = "/run/keeplane-extra-ca"


@pytest.fixture(scope="module")
def parse():
    from tests.integration.test_chart_network_policies import parse

    return parse


def with_trust(values, **bundle):
    values["trust"] = {"extraCaBundle": {"key": "ca.crt", **bundle}}
    return values


def pod_spec(chart, parse, output, kind, name):
    return parse(workload(chart, output, kind, name))["spec"]["template"]["spec"]


def named(entries, name):
    return next(entry for entry in entries if entry["name"] == name)


def file_mode(value):
    """A rendered octal mode such as 0440, which the small reader keeps as digits."""
    return int(str(value), 8)


def env_values(container):
    return {entry["name"]: entry.get("value") for entry in container.get("env", [])}


def check_app_trusts_the_bundle(spec, source, source_name, key="ca.crt"):
    app = named(spec["containers"], "app")
    assert env_values(app)["SSL_CERT_FILE"] == BUNDLE
    assert {"name": "keeplane-trust", "mountPath": "/run/keeplane-trust",
            "readOnly": True} in app["volumeMounts"]
    # The app never mounts the source itself, only the combined file.
    assert all(mount["name"] != "keeplane-extra-ca" for mount in app["volumeMounts"])
    init = named(spec["initContainers"], "prepare-trust-bundle")
    assert init["image"] == app["image"]
    assert init["command"] == ["python", "/app/prepare_trust_bundle.py",
                               EXTRA + "/ca.crt", BUNDLE]
    assert init["securityContext"]["runAsUser"] == 65532
    assert init["securityContext"]["runAsNonRoot"] is True
    assert init["securityContext"]["readOnlyRootFilesystem"] is True
    assert {"name": "keeplane-extra-ca", "mountPath": EXTRA,
            "readOnly": True} in init["volumeMounts"]
    volumes = {volume["name"]: volume for volume in spec["volumes"]}
    origin = volumes["keeplane-extra-ca"][source]
    assert origin["secretName" if source == "secret" else "name"] == source_name
    # Only the named key is mounted, as ca.crt, readable through the fsGroup.
    assert origin["items"] == [{"key": key, "path": "ca.crt"}]
    assert file_mode(origin["defaultMode"]) == 0o440
    assert spec["securityContext"]["fsGroup"] == 65532
    assert volumes["keeplane-trust"]["emptyDir"]["medium"] == "Memory"


def test_co_h6_managed_mode_app_and_every_gateway_copy_add_the_extra_cas(
        chart, parse, tmp_path):
    values = with_trust(chart.postgres_values("managed"), secretName="model-endpoint-ca",
                        key="bundle.pem")
    for copies, enroller in ((2, False), (3, True)):
        values["gateway"]["copies"] = copies
        if enroller:
            from tests.integration.test_chart_model_enroller import with_enroller

            values = with_enroller(values, copies=copies)
        output = rendered(render(chart, tmp_path, values))
        check_app_trusts_the_bundle(
            pod_spec(chart, parse, output, "Deployment", "keeplane-app"),
            "secret", "model-endpoint-ca", key="bundle.pem")
        copy = pod_spec(chart, parse, output, "StatefulSet", "keeplane-gateway")
        gateway = named(copy["containers"], "agentgateway")
        variables = env_values(gateway)
        # The image's own SSL_CERT_FILE (its system CAs) stays; the extra
        # CAs come from the folder SSL_CERT_DIR names.
        assert variables["SSL_CERT_DIR"] == EXTRA
        assert "SSL_CERT_FILE" not in variables
        assert {"name": "keeplane-extra-ca", "mountPath": EXTRA,
                "readOnly": True} in gateway["volumeMounts"]
        source = named(copy["volumes"], "keeplane-extra-ca")["secret"]
        assert source["secretName"] == "model-endpoint-ca"
        assert source["items"] == [{"key": "bundle.pem", "path": "ca.crt"}]
        # The gateway has no fsGroup: the one public CA file is world-readable.
        assert file_mode(source["defaultMode"]) == 0o444
        assert "fsGroup" not in (copy.get("securityContext") or {})
        # Nothing else in the copy's pod gets the bundle, the enroller included.
        for container in copy["containers"] + copy.get("initContainers", []):
            if container["name"] != "agentgateway":
                assert "SSL_CERT_DIR" not in env_values(container)
    # The chart only references the bundle; it never renders it.
    assert all(chart.name_of(doc) != "model-endpoint-ca"
               for doc in chart.of_kind(output, "Secret") + chart.of_kind(output, "ConfigMap"))


def test_co_h7_existing_mode_only_the_app_adds_the_extra_cas(chart, parse, tmp_path):
    values = with_trust(existing_with_ca(chart), configMapName="model-endpoint-ca")
    output = rendered(render(chart, tmp_path, values))
    check_app_trusts_the_bundle(
        pod_spec(chart, parse, output, "Deployment", "keeplane-app"),
        "configMap", "model-endpoint-ca")
    assert not chart.of_kind(output, "StatefulSet")
    # The customer-run gateway's own CA keeps its separate setting and file.
    app = named(pod_spec(chart, parse, output, "Deployment", "keeplane-app")["containers"],
                "app")
    assert env_values(app)["KEEPLANE_GATEWAY_CA_FILE"] == "/run/keeplane-gateway-ca/ca.crt"
    preflight = workload(chart, output, "Job", "keeplane-existing-gateway-preflight")
    assert "SSL_CERT" not in preflight and "keeplane-extra-ca" not in preflight


def test_co_h8_without_an_extra_bundle_nothing_changes(chart, tmp_path):
    for values in (chart.postgres_values("managed"), chart.postgres_values("existing"),
                   with_trust(chart.postgres_values("managed"))):
        output = rendered(render(chart, tmp_path, values))
        for absent in ("SSL_CERT_FILE", "SSL_CERT_DIR", "keeplane-extra-ca",
                       "keeplane-trust", "prepare-trust-bundle"):
            assert absent not in output, absent


def test_co_h9_helm_refuses_a_malformed_reference(chart, tmp_path):
    refusals = [
        ({"secretName": "a-ca", "configMapName": "a-ca"},
         "set secretName or configMapName, not both"),
        ({"secretName": "Model_CA"}, "trust.extraCaBundle.secretName \"Model_CA\""),
        ({"configMapName": "ca/bundle"}, "trust.extraCaBundle.configMapName \"ca/bundle\""),
        ({"secretName": "-ca"}, "is not a Kubernetes object name"),
        ({"secretName": "a" * 254}, "is not a Kubernetes object name"),
        ({"secretName": "a-ca", "key": ""}, "trust.extraCaBundle.key \"\""),
        ({"secretName": "a-ca", "key": "../ca.crt"}, "trust.extraCaBundle.key \"../ca.crt\""),
        ({"secretName": "a-ca", "key": ".."}, "is not a Secret or ConfigMap key"),
    ]
    for bundle, message in refusals:
        values = chart.postgres_values("managed")
        values["trust"] = {"extraCaBundle": bundle}
        result = render(chart, tmp_path, values)
        assert result.returncode != 0, bundle
        assert message in result.stderr, (bundle, result.stderr)
    # The schema refuses unknown fields and other types before any template runs.
    for bundle in ({"secret": "a-ca"}, {"secretName": ["a-ca"]}, {"key": 1}):
        values = chart.postgres_values("managed")
        values["trust"] = {"extraCaBundle": bundle}
        result = render(chart, tmp_path, values)
        assert result.returncode != 0 and "trust" in result.stderr, (bundle, result.stderr)


def test_co_h10_the_gateway_s_system_cas_cannot_be_replaced_alongside_it(chart, tmp_path):
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        values = with_trust(chart.postgres_values("managed"), secretName="model-endpoint-ca")
        values["agentgateway-standalone"]["extraEnv"].append(
            {"name": name, "value": "/run/elsewhere/ca.pem"})
        result = render(chart, tmp_path, values)
        assert result.returncode != 0
        assert f"Leave {name} out of agentgateway-standalone.extraEnv" in result.stderr
        # Existing mode runs no gateway, so the bundled chart's values don't matter.
        values = with_trust(chart.postgres_values("existing"), secretName="model-endpoint-ca")
        values["agentgateway-standalone"]["extraEnv"].append(
            {"name": name, "value": "/run/elsewhere/ca.pem"})
        rendered(render(chart, tmp_path, values))


def test_co_h11_the_kind_preview_trusts_its_fixture_provider_over_https(chart, parse):
    output = chart.render("keeplane", *chart.LOCAL)
    # The local trial's app has a shell script the small YAML reader skips, so
    # it is read line by line here.
    app_pod = workload(chart, output, "Deployment", "keeplane-app")
    app = next(item for item in chart.containers(app_pod)
               if chart.scalar(item, "name") == "app")
    variables = {name: value for name, value, _ in chart.env(app)}
    assert variables["SSL_CERT_FILE"] == BUNDLE
    assert variables["PREVIEW_OPENAI_BASE_URL"] == "https://cloud-provider:18443/v1"
    assert variables["PREVIEW_ANTHROPIC_BASE_URL"] == "https://cloud-provider:18443/v1"
    assert [chart.scalar(item, "name") for item in chart.containers(app_pod, "initContainers")
            ][-1] == "prepare-trust-bundle"
    assert chart.volumes(app_pod)["keeplane-extra-ca"][0] == "configMap"
    assert 'name: "cloud-provider-ca"' in app_pod
    copy = pod_spec(chart, parse, output, "StatefulSet", "keeplane-gateway")
    assert env_values(named(copy["containers"], "agentgateway"))["SSL_CERT_DIR"] == EXTRA
    assert named(copy["volumes"], "keeplane-extra-ca")["configMap"]["name"] == "cloud-provider-ca"
