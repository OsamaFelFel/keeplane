"""Render the opt-in ingress and egress NetworkPolicies and check what they allow.

Rendering proves what the chart asks Kubernetes to create, not that a cluster
enforces it. See chart-network-policies-cases.md.
"""

import copy
import json
import re

import pytest

from tests.integration.test_chart_installation_shape import (
    name_of,
    pod_labels,
    postgres_values,
    workloads,
)
from tests.integration.test_chart_package import CHART, manifests, run

RELEASE = "pg"
LOCAL = "deploy/local/values.yaml"
DNS = {"namespaceSelector": {"kubernetes.io/metadata.name": "kube-system"},
       "podSelector": {"k8s-app": "kube-dns"}}
PUBLIC_ENTRY = {"namespaceSelector": {"kubernetes.io/metadata.name": "ingress-nginx"},
                "podSelector": {"app.kubernetes.io/name": "ingress-nginx"}}
MODELS = [{"cidr": "203.0.113.0/24", "ports": [443]},
          {"namespaceSelector": {"kubernetes.io/metadata.name": "models"},
           "podSelector": {"app": "qwen"}, "ports": [8080]}]
APP_DATABASE = [{"cidr": "10.20.0.5/32", "ports": [5432]}]
GATEWAY_DATABASE = [{"namespaceSelector": {"kubernetes.io/metadata.name": "database"},
                     "podSelector": {"app": "gateway-db"}, "ports": [5432]}]
SUPPLIED = [{"namespaceSelector": {"kubernetes.io/metadata.name": "gateway"},
             "podSelector": {"app": "customer-gateway"}, "ports": [4000]}]
RUNNERS = [{"podSelector": {"app": "qwen"}, "ports": [8080, 8081]}]
GATEWAY_PODS = {"app.kubernetes.io/name": "agentgateway-standalone",
                "app.kubernetes.io/instance": RELEASE}


# --- A reader for the block YAML that Helm prints for these policies. ------------
# The repository's tests carry no YAML dependency; NetworkPolicy documents use
# only mappings, sequences and plain or quoted scalars.

KEY = re.compile(r'^("(?:[^"\\]|\\.)*"|[^\s"\'\[{#-][^:]*|-[^\s:][^:]*):(?: (.*)|)$')


def scalar(text):
    text = text.strip()
    if text.startswith('"'):
        return json.loads(text)
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    if text == "[]":
        return []
    if text == "{}":
        return {}
    if text.startswith("[") and text.endswith("]"):
        return [scalar(part) for part in text[1:-1].split(",")]
    if re.fullmatch(r"-?[0-9]+", text):
        return int(text)
    return {"true": True, "false": False, "null": None, "~": None}.get(text, text)


def parse(text):
    lines = [[len(raw) - len(raw.lstrip(" ")), raw.strip()] for raw in text.splitlines()
             if raw.strip() and not raw.lstrip().startswith("#")]
    if not lines:
        return None
    value, end = node(lines, 0, lines[0][0])
    assert end == len(lines), ("Unread YAML", lines[end:])
    return value


def is_item(line):
    return line[1] == "-" or line[1].startswith("- ")


def node(lines, index, level):
    return (sequence if is_item(lines[index]) else mapping)(lines, index, level)


def sequence(lines, index, level):
    found = []
    while index < len(lines) and lines[index][0] == level and is_item(lines[index]):
        rest = lines[index][1][1:].strip()
        if not rest:
            index += 1
            value, index = node(lines, index, lines[index][0])
        elif KEY.match(rest):
            lines[index] = [level + 2, rest]
            value, index = mapping(lines, index, level + 2)
        else:
            value, index = scalar(rest), index + 1
        found.append(value)
    return found, index


def mapping(lines, index, level):
    found = {}
    while index < len(lines) and lines[index][0] == level and not is_item(lines[index]):
        match = KEY.match(lines[index][1])
        assert match, ("Not a mapping line", lines[index])
        key = scalar(match.group(1))
        rest = (match.group(2) or "").strip()
        index += 1
        if rest:
            found[key] = scalar(rest)
        elif index < len(lines) and lines[index][0] > level:
            found[key], index = node(lines, index, lines[index][0])
        elif index < len(lines) and lines[index][0] == level and is_item(lines[index]):
            found[key], index = sequence(lines, index, level)
        else:
            found[key] = None
    return found, index


# --- Rendering ---------------------------------------------------------------------

def merged(base, extra):
    result = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merged(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def postgres(mode="managed", **policy):
    """The documented PostgreSQL installation with only the given policy settings."""
    values = postgres_values(mode)
    values["networkPolicy"] = {"gatewayIngressEnabled": False, **policy}
    return values


def egress(mode="managed", postgres_on=True, **lists):
    """Every egress list the installation needs, overridable per list."""
    found = {"modelEndpoints": MODELS}
    if postgres_on:
        found["postgres"] = APP_DATABASE
    found["gatewayDatabase" if mode == "managed" else "suppliedGateway"] = (
        GATEWAY_DATABASE if mode == "managed" else SUPPLIED)
    found.update(lists)
    return {key: value for key, value in found.items() if value is not None}


def render(values=None, *args, local=False, release=RELEASE, tmp_path=None):
    files = []
    if local:
        files += ["-f", LOCAL]
    if values is not None:
        path = tmp_path / f"values-{len(list(tmp_path.iterdir()))}.json"
        path.write_text(json.dumps(values))
        files += ["-f", str(path)]
    return run("template", release, CHART, *files, *args)


def rendered(result):
    assert result.returncode == 0, result.stderr
    return result.stdout


def policies(output):
    found = {}
    for document in manifests(output):
        if re.search(r"^kind: NetworkPolicy$", document, re.MULTILINE):
            parsed = parse(document)
            found[parsed["metadata"]["name"]] = parsed
    return found


def refused(result, *phrases):
    return result.returncode != 0 and all(phrase in result.stderr for phrase in phrases)


def rule(peer, *ports, protocol="TCP"):
    return {"to": [peer], "ports": [{"protocol": protocol, "port": port} for port in ports]}


def destination_rules(entries):
    rules = []
    for entry in entries:
        if "cidr" in entry:
            peer = {"ipBlock": {"cidr": entry["cidr"]}}
        else:
            peer = {key: {"matchLabels": entry[key]}
                    for key in ("namespaceSelector", "podSelector") if key in entry}
        rules.append(rule(peer, *entry["ports"]))
    return rules


def dns_rule(selectors=DNS):
    peer = {key: {"matchLabels": value} for key, value in selectors.items()}
    return {"to": [peer], "ports": [{"protocol": "UDP", "port": 53},
                                     {"protocol": "TCP", "port": 53}]}


def selected(policy, labels):
    wanted = policy["spec"]["podSelector"].get("matchLabels") or {}
    return bool(wanted) and all(labels.get(key) == value for key, value in wanted.items())


@pytest.fixture
def make(tmp_path):
    def build(values=None, *args, **kwargs):
        return render(values, *args, tmp_path=tmp_path, **kwargs)
    return build


# --- Cases -------------------------------------------------------------------------

def test_policies_stay_off_by_default_and_values_are_checked(make):
    """NETPOL-01"""
    for result in (make(postgres("managed")), make(postgres("existing")),
                   make(local=True)):
        assert policies(rendered(result)) == {}
    bad = {
        "typo": {"egressEnabeld": True},
        "cidr": {"egress": {"modelEndpoints": [{"cidr": "api.example.test", "ports": [443]}]}},
        "no-ports": {"egress": {"modelEndpoints": [{"cidr": "203.0.113.0/24"}]}},
        "port-text": {"egress": {"modelEndpoints": [{"cidr": "203.0.113.0/24",
                                                     "ports": ["https"]}]}},
        "port-range": {"egress": {"modelEndpoints": [{"cidr": "203.0.113.0/24",
                                                      "ports": [70000]}]}},
        "selector-value": {"publicEntry": {"podSelector": {"app": 3}}},
        "unknown-field": {"egress": {"modelEndpoints": [{"host": "api.example.test",
                                                         "ports": [443]}]}},
    }
    for label, policy in bad.items():
        assert make(postgres("managed", **policy)).returncode != 0, label


def test_app_ingress_admits_only_the_public_entry(make):
    """NETPOL-02"""
    for mode in ("managed", "existing"):
        output = rendered(make(postgres(mode, appIngressEnabled=True,
                                        publicEntry=PUBLIC_ENTRY)))
        found = policies(output)
        assert set(found) == {"pg-app-ingress"}, mode
        spec = found["pg-app-ingress"]["spec"]
        assert spec == {
            "podSelector": {"matchLabels": {"app": "pg-app"}},
            "policyTypes": ["Ingress"],
            "ingress": [{
                "from": [{key: {"matchLabels": value}
                          for key, value in PUBLIC_ENTRY.items()}],
                "ports": [{"protocol": "TCP", "port": 3000}],
            }],
        }, mode
        pods = {name_of(doc): pod_labels(doc) for doc in workloads(output)}
        assert [name for name, labels in pods.items()
                if selected(found["pg-app-ingress"], labels)] == ["pg-app"], pods
    # A pod selector alone stays in the release namespace.
    only_pods = {"podSelector": {"app": "edge-proxy"}}
    spec = policies(rendered(make(postgres(
        appIngressEnabled=True, publicEntry=only_pods))))["pg-app-ingress"]["spec"]
    assert spec["ingress"][0]["from"] == [{"podSelector": {"matchLabels": {"app": "edge-proxy"}}}]


def test_app_ingress_refuses_a_missing_entry_or_an_exposed_service(make):
    """NETPOL-03"""
    assert refused(make(postgres(appIngressEnabled=True)),
                   "networkPolicy.publicEntry.namespaceSelector or podSelector")
    no_ingress = postgres(appIngressEnabled=True, publicEntry=PUBLIC_ENTRY)
    no_ingress["ingress"] = {"enabled": False}
    no_ingress["app"]["postgres"]["publicOrigin"] = "https://keeplane.example.test"
    no_ingress["app"]["service"] = {"type": "NodePort", "nodePort": 30080}
    assert refused(make(no_ingress), "app.service.type=ClusterIP")
    # The local trial publishes the app on a NodePort, so it cannot turn this on.
    assert refused(make(None, "--set", "networkPolicy.appIngressEnabled=true",
                        "--set-json", "networkPolicy.publicEntry=" + json.dumps(PUBLIC_ENTRY),
                        local=True), "app.service.type=ClusterIP")


def test_app_egress_reaches_only_what_the_app_calls(make):
    """NETPOL-04"""
    output = rendered(make(postgres(egressEnabled=True,
                                    egress=egress(runners=RUNNERS))))
    found = policies(output)
    assert set(found) == {"pg-app-egress", "pg-gateway-egress", "pg-accounts-migrate-egress"}
    spec = found["pg-app-egress"]["spec"]
    assert spec["podSelector"] == {"matchLabels": {"app": "pg-app"}}
    assert spec["policyTypes"] == ["Egress"]
    assert spec["egress"] == [
        dns_rule(),
        rule({"podSelector": {"matchLabels": GATEWAY_PODS}}, 4000),
        *destination_rules(APP_DATABASE),
        *destination_rules(MODELS),
        *destination_rules(RUNNERS),
    ]
    # Without runners listed, the app gets no runner rule.
    spec = policies(rendered(make(postgres(egressEnabled=True, egress=egress()))))[
        "pg-app-egress"]["spec"]
    assert spec["egress"] == [dns_rule(), rule({"podSelector": {"matchLabels": GATEWAY_PODS}}, 4000),
                              *destination_rules(APP_DATABASE), *destination_rules(MODELS)]


def test_gateway_copies_reach_only_dns_their_database_and_models(make):
    """NETPOL-05"""
    output = rendered(make(postgres(egressEnabled=True, egress=egress(runners=RUNNERS))))
    policy = policies(output)["pg-gateway-egress"]
    assert policy["spec"] == {
        "podSelector": {"matchLabels": GATEWAY_PODS},
        "policyTypes": ["Egress"],
        "egress": [dns_rule(), *destination_rules(GATEWAY_DATABASE),
                   *destination_rules(MODELS)],
    }
    pods = {name_of(doc): pod_labels(doc) for doc in workloads(output)}
    assert sorted(name for name, labels in pods.items() if selected(policy, labels)) == [
        "pg", "pg-gateway"], pods  # the zero-replica bundled Deployment and the copies
    assert "pg-app" not in json.dumps(policy)


def test_migration_job_reaches_only_dns_and_postgres_before_it_runs(make):
    """NETPOL-06"""
    output = rendered(make(postgres(egressEnabled=True, egress=egress())))
    policy = policies(output)["pg-accounts-migrate-egress"]
    annotations = policy["metadata"]["annotations"]
    assert annotations == {"helm.sh/hook": "pre-install,pre-upgrade",
                           "helm.sh/hook-weight": "-20",
                           "helm.sh/hook-delete-policy": "before-hook-creation"}
    job = next(doc for doc in workloads(output) if name_of(doc) == "pg-accounts-migrate")
    weight = re.search(r'"helm.sh/hook-weight": "(-?\d+)"', job).group(1)
    assert int(annotations["helm.sh/hook-weight"]) < int(weight)
    assert policy["spec"] == {
        "podSelector": {"matchLabels": {"app": "pg-accounts-migrate"}},
        "policyTypes": ["Egress"],
        "egress": [dns_rule(), *destination_rules(APP_DATABASE)],
    }
    pods = {name_of(doc): pod_labels(doc) for doc in workloads(output)}
    assert [name for name, labels in pods.items() if selected(policy, labels)] == [
        "pg-accounts-migrate"]
    # External migrations: no Job, so no Job policy.
    external = postgres(egressEnabled=True, egress=egress())
    external["app"]["postgres"]["migration"]["enabled"] = False
    assert "pg-accounts-migrate-egress" not in policies(rendered(make(external)))


def test_existing_gateway_mode_restricts_only_keeplane_pods(make):
    """NETPOL-07"""
    output = rendered(make(postgres("existing", egressEnabled=True,
                                    egress=egress("existing"))))
    found = policies(output)
    assert set(found) == {"pg-app-egress", "pg-accounts-migrate-egress",
                          "pg-gateway-preflight-egress"}
    assert found["pg-app-egress"]["spec"]["egress"] == [
        dns_rule(), *destination_rules(SUPPLIED), *destination_rules(APP_DATABASE),
        *destination_rules(MODELS)]
    preflight = found["pg-gateway-preflight-egress"]
    assert preflight["metadata"]["annotations"]["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert preflight["spec"] == {
        "podSelector": {"matchLabels": {"app": "pg-gateway-preflight"}},
        "policyTypes": ["Egress"],
        "egress": [dns_rule(), *destination_rules(SUPPLIED)],
    }
    assert "agentgateway-standalone" not in output
    # A supplied gateway reached by address range works the same way.
    by_address = [{"cidr": "10.96.40.0/24", "ports": [4000]}]
    spec = policies(rendered(make(postgres("existing", egressEnabled=True, egress=egress(
        "existing", suppliedGateway=by_address)))))["pg-app-egress"]["spec"]
    assert spec["egress"][1] == destination_rules(by_address)[0]
    # The chart creates no policy for a gateway it does not install.
    assert refused(make(postgres("existing", gatewayIngressEnabled=True)),
                   "gatewayIngressEnabled belongs to managed mode")
    assert refused(make(postgres("existing", egress={"gatewayDatabase": GATEWAY_DATABASE})),
                   "networkPolicy.egress.gatewayDatabase belongs to managed mode")


def test_incomplete_or_contradictory_policy_settings_are_refused(make):
    """NETPOL-08"""
    on = {"egressEnabled": True}
    cases = {
        "managed without models": (postgres(**on, egress=egress(modelEndpoints=None)),
                                   "needs networkPolicy.egress.modelEndpoints"),
        "existing without models": (postgres("existing", **on, egress=egress(
            "existing", modelEndpoints=None)), "needs networkPolicy.egress.modelEndpoints"),
        "without app database": (postgres(**on, egress=egress(postgres=None)),
                                 "needs networkPolicy.egress.postgres"),
        "without gateway database": (postgres(**on, egress=egress(gatewayDatabase=None)),
                                     "needs networkPolicy.egress.gatewayDatabase"),
        "existing without supplied gateway": (postgres("existing", **on, egress=egress(
            "existing", suppliedGateway=None)), "needs networkPolicy.egress.suppliedGateway"),
        "supplied gateway in managed mode": (postgres(egress={"suppliedGateway": SUPPLIED}),
                                             "suppliedGateway belongs to existing mode"),
        "both address and selector": (postgres(**on, egress=egress(modelEndpoints=[
            {"cidr": "203.0.113.0/24", "podSelector": {"app": "qwen"}, "ports": [443]}])),
            "use either cidr or namespaceSelector/podSelector"),
        "empty selector": (postgres(**on, egress=egress(modelEndpoints=[
            {"podSelector": {}, "ports": [443]}])), "an empty selector would match everything"),
        "dns cleared": (postgres(**on, egress=egress(),
                                 dns={"namespaceSelector": None, "podSelector": None}),
                        "networkPolicy.dns: each entry needs a cidr"),
        "read-only gateway with database": (merged(postgres(egress={
            "gatewayDatabase": GATEWAY_DATABASE}), {"agentgateway-standalone": {
                "mode": "readonly", "database": {"postgres": {"url": ""}}}}),
            "needs agentgateway-standalone.mode=database"),
    }
    for label, (values, phrase) in cases.items():
        assert refused(make(values), phrase), (label, make(values).stderr)
    assert refused(make(None, "--set", "networkPolicy.egressEnabled=true",
                        "--set-json", "networkPolicy.egress.modelEndpoints=" + json.dumps(MODELS),
                        "--set-json", "networkPolicy.egress.postgres=" + json.dumps(APP_DATABASE),
                        "--set-json", "networkPolicy.egress.gatewayDatabase="
                        + json.dumps(GATEWAY_DATABASE), local=True),
                   "app.postgres.enabled is false")


def test_local_trial_and_read_only_gateway_need_no_database_rules(make):
    """NETPOL-09"""
    output = rendered(make(None, "--set", "networkPolicy.egressEnabled=true",
                           "--set-json", "networkPolicy.egress.modelEndpoints=" + json.dumps(MODELS),
                           "--set-json", "networkPolicy.egress.gatewayDatabase="
                           + json.dumps(GATEWAY_DATABASE), local=True))
    found = policies(output)
    assert set(found) == {"pg-app-egress", "pg-gateway-egress"}
    assert found["pg-app-egress"]["spec"]["egress"] == [
        dns_rule(), rule({"podSelector": {"matchLabels": GATEWAY_PODS}}, 4000),
        *destination_rules(MODELS)]
    readonly = merged(postgres(egressEnabled=True, egress=egress(gatewayDatabase=None)),
                      {"agentgateway-standalone": {"mode": "readonly",
                                                   "database": {"postgres": {"url": ""}}}})
    gateway = policies(rendered(make(readonly)))["pg-gateway-egress"]
    assert gateway["spec"]["egress"] == [dns_rule(), *destination_rules(MODELS)]
    # A DNS server given by address, such as a node-local cache.
    dns = {"cidr": "169.254.20.10/32"}
    spec = policies(rendered(make(postgres(
        egressEnabled=True, egress=egress(),
        dns={"namespaceSelector": None, "podSelector": None, **dns}))))["pg-app-egress"]["spec"]
    assert spec["egress"][0]["to"] == [{"ipBlock": {"cidr": "169.254.20.10/32"}}]


def test_every_keeplane_pod_is_restricted_when_egress_is_on(make):
    """NETPOL-10"""
    for mode in ("managed", "existing"):
        output = rendered(make(postgres(mode, gatewayIngressEnabled=mode == "managed",
                                        appIngressEnabled=True, publicEntry=PUBLIC_ENTRY,
                                        egressEnabled=True, egress=egress(mode))))
        found = policies(output)
        outbound = [policy for policy in found.values()
                    if "Egress" in policy["spec"]["policyTypes"]]
        pods = {name_of(doc): pod_labels(doc) for doc in workloads(output)}
        assert pods
        unrestricted = [name for name, labels in pods.items()
                        if not any(selected(policy, labels) for policy in outbound)]
        assert unrestricted == [], (mode, unrestricted)
        for policy in found.values():
            for item in policy["spec"].get("egress", []) + policy["spec"].get("ingress", []):
                for peer in item.get("to", []) + item.get("from", []):
                    assert peer, policy["metadata"]["name"]  # never an empty peer
                    if "ipBlock" not in peer:
                        assert any(peer[key]["matchLabels"] for key in peer), peer
                assert item.get("ports"), policy["metadata"]["name"]
