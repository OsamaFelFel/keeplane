"""Render the chart and check how certificates reach Keeplane and the ingress.

Cases CO-H1 to CO-H4 in chart-certificates-cases.md. Rendering proves what
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
