"""Render how developers reach the managed gateway's protected runtime (ADR 016, 018, 027).

Cases PA-01 to PA-09 in chart-protected-access-cases.md. All but PA-06 and
PA-09 render the chart with Helm and are skipped when Helm is missing; PA-06 and
PA-09 read only the values file, the guides and the CLI code and always run.
"""

import copy
import inspect
import json
import re
from pathlib import Path

import pytest

from components.cli import coding, credential_profile, keeplane, opencode_adapter
from tests.integration.test_chart_model_enroller import RELEASE, with_enroller

ROOT = Path(__file__).resolve().parents[2]
VALUES = ROOT / "deploy/helm/keeplane/values.yaml"
REFERENCE = ROOT / "docs/guide/kubernetes-installation-reference.md"
QUICKSTART = ROOT / "docs/guide/cli-quickstart.md"
RUNTIME_SERVICE = f"{RELEASE}-gateway-runtime"
RUNTIME_INGRESS = f"{RELEASE}-gateway-runtime"
PROTECTED_PATH = "/v1/chat/completions"
PRIVATE_PORTS = {4000, 15000, 15020, 15021}
COPY_SELECTOR = {"app.kubernetes.io/name": "agentgateway-standalone",
                 "app.kubernetes.io/instance": RELEASE,
                 "app.kubernetes.io/component": "standalone"}
PUBLIC_ENTRY = {"namespaceSelector": {"kubernetes.io/metadata.name": "ingress-nginx"},
                "podSelector": {"app.kubernetes.io/name": "ingress-nginx"}}


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


def parsed_of_kind(chart, policy, output, kind):
    return {chart.name_of(doc): policy.parse(doc) for doc in chart.of_kind(output, kind)}


def service_ports(chart, output):
    """Every Service's ports and target ports, read as SHAPE-02 reads them."""
    found = {}
    for service in chart.of_kind(output, "Service"):
        ports = chart.items(chart.block(chart.block(service, "spec"), "ports"))
        found[chart.name_of(service)] = sorted(
            {int(chart.scalar(port, "port")) for port in ports}
            | {int(chart.scalar(port, "targetPort") or chart.scalar(port, "port"))
               for port in ports})
    return found


def ingress_paths(chart, policy, output):
    """(host, path, pathType, service, port) for every Ingress rule."""
    found = []
    for ingress in parsed_of_kind(chart, policy, output, "Ingress").values():
        for rule in ingress["spec"]["rules"]:
            for path in rule["http"]["paths"]:
                backend = path["backend"]["service"]
                found.append((rule["host"], path["path"], path["pathType"],
                              backend["name"], backend["port"]["number"]))
    return found


def renders(chart, make):
    """Every supported install, with the enroller off by default."""
    return {
        "postgres-managed": rendered(make(managed(chart))),
        "postgres-existing": rendered(make(chart.postgres_values("existing"))),
        "local-managed": rendered(make(None, "-f", "deploy/local/values.yaml")),
        "local-existing": rendered(make(None, "-f", "deploy/local/existing-values.yaml")),
    }


# --- Cases -------------------------------------------------------------------------


def test_pa_01_without_the_enroller_nothing_publishes_the_protected_port(
        chart, policy, make):
    for name, output in renders(chart, make).items():
        services = service_ports(chart, output)
        assert not [service for service in services if service.endswith("-gateway-runtime")]
        assert all(5000 not in ports for ports in services.values()), name
        assert all(path[1] != PROTECTED_PATH and path[4] != 5000
                   for path in ingress_paths(chart, policy, output)), name
        assert "port: 5000" not in output, name


def test_pa_02_the_enroller_adds_one_cluster_service_for_port_5000_only(
        chart, policy, make):
    output = rendered(make(with_enroller(managed(chart))))
    runtime = next(policy.parse(doc) for doc in chart.of_kind(output, "Service")
                   if chart.name_of(doc) == RUNTIME_SERVICE)
    spec = runtime["spec"]
    assert spec["type"] == "ClusterIP"
    assert "clusterIP" not in spec  # an ordinary address, not headless
    assert spec["selector"] == COPY_SELECTOR
    assert spec["ports"] == [{"name": "protected", "protocol": "TCP",
                              "port": 5000, "targetPort": 5000}]
    # The copies' selector matches exactly the StatefulSet's pods.
    copies = next(doc for doc in chart.of_kind(output, "StatefulSet")
                  if chart.name_of(doc) == f"{RELEASE}-gateway")
    assert all(chart.pod_labels(copies)[key] == value for key, value in COPY_SELECTOR.items())
    # Every other Service is unchanged: 5000 is only here, and no Service
    # carries an admin, stats or readiness port.
    assert service_ports(chart, output) == {
        f"{RELEASE}-app": [3000],
        RELEASE: [4000],
        f"{RELEASE}-gateway-copies": [4000],
        RUNTIME_SERVICE: [5000],
    }
    # The app, the copies and the jobs declare no new container port.
    assert set(re.findall(r"containerPort: (\d+)", output)) == set(re.findall(
        r"containerPort: (\d+)", rendered(make(managed(chart)))))


def test_pa_03_the_one_public_host_routes_only_the_protected_path_to_the_gateway(
        chart, policy, make):
    values = with_enroller(managed(chart))
    values["ingress"]["annotations"] = {"example.test/one": "yes"}
    output = rendered(make(values))
    ingresses = parsed_of_kind(chart, policy, output, "Ingress")
    assert sorted(ingresses) == [f"{RELEASE}-app", RUNTIME_INGRESS]
    # Both on the one host, with the same class and TLS Secret, one rule each.
    for ingress in ingresses.values():
        spec = ingress["spec"]
        assert spec["ingressClassName"] == "nginx"
        assert spec["tls"] == [{"hosts": ["keeplane.example.test"],
                                "secretName": "keeplane-tls"}]
        assert len(spec["rules"]) == 1
    # The app's Ingress carries only "/"; the protected path is only on its own.
    assert sorted(ingress_paths(chart, policy, output)) == sorted([
        ("keeplane.example.test", PROTECTED_PATH, "Exact", RUNTIME_SERVICE, 5000),
        ("keeplane.example.test", "/", "Prefix", f"{RELEASE}-app", 3000),
    ])
    assert ingresses[f"{RELEASE}-app"]["spec"]["rules"][0]["http"]["paths"] == [
        {"path": "/", "pathType": "Prefix",
         "backend": {"service": {"name": f"{RELEASE}-app", "port": {"number": 3000}}}}]
    assert ingresses[RUNTIME_INGRESS]["spec"]["rules"][0]["http"]["paths"] == [
        {"path": PROTECTED_PATH, "pathType": "Exact",
         "backend": {"service": {"name": RUNTIME_SERVICE, "port": {"number": 5000}}}}]
    # ingress.annotations stay on the app's Ingress.
    assert ingresses[f"{RELEASE}-app"]["metadata"]["annotations"] == {"example.test/one": "yes"}
    assert "annotations" not in ingresses[RUNTIME_INGRESS]["metadata"]
    # No backend is a gateway port other than the protected one.
    assert all(path[4] not in PRIVATE_PORTS for path in ingress_paths(chart, policy, output))
    # Without the chart's Ingress the Service still renders for your own edge.
    values["ingress"]["enabled"] = False
    # The app then takes its HTTPS address from the installer, not the Ingress.
    values["app"]["postgres"]["publicOrigin"] = "https://keeplane.example.test"
    output = rendered(make(values))
    assert not chart.of_kind(output, "Ingress")
    assert service_ports(chart, output)[RUNTIME_SERVICE] == [5000]


def test_pa_04_the_gateway_policy_admits_only_the_public_entry_on_port_5000(
        chart, policy, make):
    def gateway_ingress(values):
        return policy.policies(rendered(make(values)))[f"{RELEASE}-gateway-ingress"]["spec"]

    from_app = {"from": [{"podSelector": {"matchLabels": {"app": f"{RELEASE}-app"}}}],
                "ports": [{"protocol": "TCP", "port": 4000}]}
    from_entry = {"from": [{"namespaceSelector": {"matchLabels": PUBLIC_ENTRY["namespaceSelector"]},
                            "podSelector": {"matchLabels": PUBLIC_ENTRY["podSelector"]}}],
                  "ports": [{"protocol": "TCP", "port": 5000}]}

    without = managed(chart)
    without["networkPolicy"]["publicEntry"] = PUBLIC_ENTRY
    assert gateway_ingress(without)["ingress"] == [from_app]
    with_it = with_enroller(without)
    assert gateway_ingress(with_it)["ingress"] == [from_app, from_entry]
    # With pod labels only the rule stays in the release namespace.
    pods_only = copy.deepcopy(with_it)
    pods_only["networkPolicy"]["publicEntry"] = {"podSelector": PUBLIC_ENTRY["podSelector"]}
    assert gateway_ingress(pods_only)["ingress"][1] == {
        "from": [{"podSelector": {"matchLabels": PUBLIC_ENTRY["podSelector"]}}],
        "ports": [{"protocol": "TCP", "port": 5000}]}
    # The app ingress policy is unchanged by the protected port.
    both = copy.deepcopy(with_it)
    both["networkPolicy"]["appIngressEnabled"] = True
    app_rules = policy.policies(rendered(make(both)))[f"{RELEASE}-app-ingress"]["spec"]["ingress"]
    assert all(port["port"] == 3000 for rule in app_rules for port in rule["ports"])


def test_pa_05_the_enroller_with_the_gateway_policy_needs_a_public_entry(chart, make):
    values = with_enroller(managed(chart))
    values["networkPolicy"]["publicEntry"] = {}
    refused(make(values), "gateway.enroller with networkPolicy.gatewayIngressEnabled needs "
            "networkPolicy.publicEntry", "port 5000")
    values["networkPolicy"]["publicEntry"] = {"namespaceSelector": {}, "podSelector": {}}
    refused(make(values), "networkPolicy.publicEntry")
    # Without the gateway policy nothing needs to be admitted.
    values["networkPolicy"]["gatewayIngressEnabled"] = False
    rendered(make(values))
    # Without the enroller the gateway policy needs no public entry, as before.
    plain = managed(chart)
    assert plain["networkPolicy"] == {"gatewayIngressEnabled": True}
    rendered(make(plain))


def test_pa_07_the_protected_path_takes_its_own_annotations(chart, policy, make):
    app_annotations = {"nginx.ingress.kubernetes.io/proxy-body-size": "1m"}
    model_annotations = {"nginx.ingress.kubernetes.io/proxy-read-timeout": "190",
                         "nginx.ingress.kubernetes.io/proxy-body-size": "16m"}

    def annotations(values):
        found = parsed_of_kind(chart, policy, rendered(make(values)), "Ingress")
        return {name: ingress["metadata"].get("annotations") for name, ingress in found.items()}

    values = with_enroller(managed(chart))
    # Empty by default: neither Ingress carries an annotation.
    assert annotations(values) == {f"{RELEASE}-app": None, RUNTIME_INGRESS: None}
    # Each value reaches only its own Ingress.
    values["ingress"]["annotations"] = app_annotations
    values["gateway"]["protectedIngress"] = {"annotations": model_annotations}
    assert annotations(values) == {f"{RELEASE}-app": app_annotations,
                                   RUNTIME_INGRESS: model_annotations}
    only_model = copy.deepcopy(values)
    del only_model["ingress"]["annotations"]
    assert annotations(only_model) == {f"{RELEASE}-app": None,
                                       RUNTIME_INGRESS: model_annotations}
    # Without the enroller there is no protected Ingress, and its annotations
    # reach nothing.
    without = managed(chart)
    without["gateway"]["protectedIngress"] = {"annotations": model_annotations}
    assert annotations(without) == {f"{RELEASE}-app": None}
    # Without the chart's Ingress neither renders.
    off = copy.deepcopy(values)
    off["ingress"]["enabled"] = False
    off["app"]["postgres"]["publicOrigin"] = "https://keeplane.example.test"
    assert not chart.of_kind(rendered(make(off)), "Ingress")
    # Annotation values are strings, as Kubernetes requires; the schema
    # refuses a number and any other key under protectedIngress.
    for bad in ({"annotations": {"nginx.ingress.kubernetes.io/proxy-read-timeout": 190}},
                {"annotations": {}, "paths": ["/"]}):
        wrong = copy.deepcopy(values)
        wrong["gateway"]["protectedIngress"] = bad
        refused(make(wrong), "protectedIngress")


def test_pa_08_a_null_public_entry_gets_the_charts_refusal(chart, make):
    # publicEntry: null in a values file, and --set publicEntry=null, reach
    # the chart's own refusals, never a template nil-field error.
    gateway = with_enroller(managed(chart))
    gateway["networkPolicy"]["publicEntry"] = None
    app = managed(chart)
    app["networkPolicy"].update(gatewayIngressEnabled=False, appIngressEnabled=True,
                                publicEntry=None)
    app_message = ("networkPolicy.appIngressEnabled needs networkPolicy.publicEntry"
                   ".namespaceSelector or podSelector")
    gateway_message = ("gateway.enroller with networkPolicy.gatewayIngressEnabled needs "
                       "networkPolicy.publicEntry")
    with_set = with_enroller(managed(chart))
    del with_set["networkPolicy"]["publicEntry"]
    app_set = copy.deepcopy(app)
    del app_set["networkPolicy"]["publicEntry"]
    for result, message in (
            (make(gateway), gateway_message),
            (make(with_set, "--set", "networkPolicy.publicEntry=null"), gateway_message),
            (make(app), app_message),
            (make(app_set, "--set", "networkPolicy.publicEntry=null"), app_message)):
        refused(result, message)
        assert "nil pointer" not in result.stderr, result.stderr
    # Where nothing needs a public entry, null renders: the gateway policy
    # without the enroller, and the enroller without the gateway policy.
    plain = managed(chart)
    plain["networkPolicy"]["publicEntry"] = None
    rendered(make(plain))
    quiet = copy.deepcopy(gateway)
    quiet["networkPolicy"]["gatewayIngressEnabled"] = False
    rendered(make(quiet))


def test_pa_06_values_and_guides_describe_how_developers_reach_protected_models():
    values = VALUES.read_text()
    for phrase in ("<release>-gateway-runtime", "/v1/chat/completions",
                   "https://<ingress.host>/v1", "TCP 5000", "protectedIngress:",
                   "ingress.annotations stay on the app's"):
        assert phrase in values, phrase
    assert "Publishes only the Keeplane app Service" not in values
    reference = REFERENCE.read_text()
    section = reference.split("\n## Model enroller\n", 1)[1].split("\n## ", 1)[0]
    for phrase in ("<release>-gateway-runtime", "/v1/chat/completions", "https://<host>/v1",
                   "--gateway", "networkPolicy.publicEntry", "Exact", "ADR 016",
                   "gateway.protectedIngress.annotations", "proxy-read-timeout",
                   "Ingress, `<release>-gateway-runtime`"):
        assert phrase in section, phrase
    assert "app and protected path alike" not in reference
    ports = reference.split("\n## Ports\n", 1)[1].split("\n## ", 1)[0]
    assert "<release>-gateway-runtime" in ports and "/v1/chat/completions" in ports
    for stale in ("How developers reach it in Kubernetes is not decided",
                  "No Service, port declaration or Ingress",
                  "The gateway is\nnever an Ingress backend",
                  "routes\nonly to the app Service"):
        assert stale not in reference, stale


def test_pa_09_developers_get_the_cli_gateway_address_the_cli_accepts():
    reference = REFERENCE.read_text()
    section = reference.split("\n**What to give developers.**", 1)[1].split("\nEach request reaches one copy.", 1)[0]
    for phrase in ("| `https://<host>` | `keeplane login --server` |",
                   "| `https://<host>/v1` | `keeplane code --gateway` |",
                   "doesn't save it in the profile", "/chat/completions",
                   "a resumed session must use the\nsame address",
                   "`gateway.mode=existing`", "port 4000"):
        assert phrase in section, phrase
    quickstart = QUICKSTART.read_text()
    for phrase in ("KP_SERVER=https://<host>", "KP_GATEWAY=https://<host>/v1",
                   "doesn't tell the CLI its gateway address yet",
                   "a resumed session,\nmust use the same one"):
        assert phrase in quickstart, phrase
    # The profile keeps no gateway yet, so a coding turn needs --gateway; once the
    # server gives one at sign-in (task 009-02), `code` takes it from the profile.
    assert "gateway" not in inspect.getsource(credential_profile).lower()
    assert 'getattr(credential, "gateway", None)' in inspect.getsource(coding.run)
    # A session history records the gateway, so a resumed turn needs the same one.
    assert '"gateway": gateway' in inspect.getsource(opencode_adapter.run)
    assert 'code.add_argument("--gateway", help=' in inspect.getsource(keeplane.main)
    for given, used in (("https://keeplane.example/v1", "https://keeplane.example/v1"),
                        ("https://keeplane.example/v1/", "https://keeplane.example/v1"),
                        ("http://127.0.0.1:5000/v1", "http://127.0.0.1:5000/v1")):
        assert coding.gateway_endpoint(given) == used
    for refused in ("https://keeplane.example", "https://keeplane.example/",
                    "https://keeplane.example/v1/chat/completions",
                    "https://keeplane.example/v1?team=a", "http://keeplane.example/v1"):
        with pytest.raises(coding.ConnectionError):
            coding.gateway_endpoint(refused)
