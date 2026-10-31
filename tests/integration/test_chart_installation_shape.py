"""Render the chart and check the installation shape an installer relies on."""

import json
from pathlib import Path
import re
import sys
import tempfile

from tests.integration.test_chart_package import (
    CHART, ROOT, case, gateway_key_env, manifests, run,
)


IMAGE = "registry.example.test/keeplane@sha256:" + "a" * 64
GATEWAY = json.loads((ROOT / "deploy/component-manifest.json").read_text())["gateway"]
GATEWAY_IMAGE = GATEWAY["image"]
PINNED = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")
PRIVATE_GATEWAY_PORTS = {"15000", "15020", "15021"}
SENSITIVE = re.compile(r"PASSWORD|SECRET|KEY|TOKEN|CREDENTIAL")
SUPPLIED_URL = "http://customer-gateway.gateway.svc.cluster.local:4000"
UNRELATED_MODEL = "customer-unrelated-model"


def secret_env(name, secret, key):
    return {"name": name, "valueFrom": {"secretKeyRef": {"name": secret, "key": key}}}


def gateway_values():
    """Managed gateway settings in the documented Secret-backed form."""
    return {
        "database": {
            "postgres": {
                "url": "postgresql://keeplane:${KEEPLANE_DB_PASSWORD}"
                "@gateway-db.database.svc.cluster.local:5432/keeplane"
            }
        },
        "extraEnv": [
            secret_env("KEEPLANE_DB_PASSWORD", "keeplane-gateway-db", "password"),
            secret_env(
                "GATEWAY_RUNTIME_KEY_HASH", "keeplane-gateway-keys", "runtime-key-hash"
            ),
            secret_env(
                "GATEWAY_ADMIN_KEY_HASH", "keeplane-gateway-keys", "admin-key-hash"
            ),
        ],
        "extraVolumes": [
            {
                "name": "provider-keys",
                "persistentVolumeClaim": {"claimName": "keeplane-provider-keys"},
            }
        ],
        "extraVolumeMounts": [
            {"name": "provider-keys", "mountPath": "/provider-keys", "readOnly": True}
        ],
        # No key policies here: the chart supplies both (SHAPE-07).
        "config": {
            "llm": {
                "models": [
                    {
                        "name": UNRELATED_MODEL,
                        "provider": {"custom": {"formats": [{"type": "completions"}]}},
                        "params": {
                            "model": "mock-local",
                            "baseUrl": "http://model:18080/v1",
                        },
                    }
                ],
            },
        },
    }


def postgres_values(mode):
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
                "migration": {
                    "user": "keeplane_migrate",
                    "credentialsSecret": "keeplane-migration-db",
                },
            },
        },
        "ingress": {
            "enabled": True,
            "className": "nginx",
            "host": "keeplane.example.test",
            "tlsSecretName": "keeplane-tls",
        },
        "gateway": {"mode": "managed", "install": True,
                    "keysSecret": "keeplane-gateway-keys", "copies": 2},
        "networkPolicy": {"gatewayIngressEnabled": mode == "managed"},
        # Present in both modes: existing mode must ignore all of it.
        "agentgateway-standalone": gateway_values(),
    }
    if mode == "existing":
        values["gateway"].update(mode="existing", install=False, url=SUPPLIED_URL)
    return values


# Small readers for Helm's block-style output; no YAML dependency is needed.
def indent(line):
    return len(line) - len(line.lstrip(" "))


def block(lines, key):
    """Lines nested under the first `key:` (including indentless sequences)."""
    if isinstance(lines, str):
        lines = lines.splitlines()
    for number, line in enumerate(lines):
        stripped = line.strip()
        if stripped not in (key + ":", "- " + key + ":"):
            continue
        level = indent(line) + (2 if stripped.startswith("- ") else 0)
        nested = []
        for following in lines[number + 1 :]:
            if following.strip() and (
                indent(following) < level
                or (indent(following) == level and not following.lstrip().startswith("- "))
            ):
                break
            nested.append(following)
        return nested
    return []


def items(lines):
    """Split a sequence block into its items."""
    dashes = [indent(line) for line in lines if line.lstrip().startswith("- ")]
    if not dashes:
        return []
    level = min(dashes)
    found = []
    for line in lines:
        if indent(line) == level and line.lstrip().startswith("- "):
            found.append([line])
        elif found:
            found[-1].append(line)
    return ["\n".join(item) + "\n" for item in found]


def scalar(text, key):
    match = re.search(r"^\s*(?:- )?" + key + r": \"?([^\"\n]*)\"?\s*$", text, re.M)
    return match.group(1) if match else None


def kind_of(document):
    return scalar(document, "kind")


def name_of(document):
    return scalar("\n".join(block(document, "metadata")), "name")


def of_kind(output, kind):
    return [doc for doc in manifests(output) if kind_of(doc) == kind]


def workloads(output):
    return [doc for doc in manifests(output)
            if kind_of(doc) in ("Deployment", "StatefulSet", "Job")]


def containers(document, key="containers"):
    template = block(block(document, "template"), "spec")
    return items(block(template, key))


def labels(lines):
    found = {}
    for line in lines:
        key, _, value = line.strip().partition(": ")
        if key and value:
            found[key] = value.strip('"')
    return found


def pod_labels(document):
    return labels(block(block(block(document, "template"), "metadata"), "labels"))


def volumes(document):
    found = {}
    for item in items(block(block(block(document, "template"), "spec"), "volumes")):
        kind = re.search(
            r"^\s+(secret|persistentVolumeClaim|configMap|emptyDir):", item, re.M
        )
        found[scalar(item, "name")] = (
            kind.group(1) if kind else None,
            scalar(item, "claimName") or scalar(item, "secretName"),
        )
    return found


def mounts(container):
    return [
        (scalar(item, "name"), scalar(item, "mountPath"), "readOnly: true" in item)
        for item in items(block(container, "volumeMounts"))
    ]


def env(container):
    return [
        (scalar(item, "name"), scalar(item, "value"), "secretKeyRef:" in item)
        for item in items(block(container, "env"))
    ]


def images(output):
    return re.findall(r"^\s*(?:- )?image: \"?([^\"\s]+)\"?\s*$", output, re.M)


KEYS_SECRET = "keeplane-gateway-keys"
KEYS_MESSAGE = "Create a Secret in the release namespace"
GATEWAY_DB_URL = (
    "agentgateway-standalone.database.postgres.url="
    "postgresql://keeplane:${KEEPLANE_DB_PASSWORD}@db:5432/keeplane"
)


def key_refusal_arguments(managed_file):
    """Managed installs that would leave port 4000 without a key check."""
    managed = ("-f", str(managed_file))
    other_secret = json.dumps([
        secret_env("GATEWAY_RUNTIME_KEY_HASH", "other-keys", "runtime-key-hash"),
        secret_env("GATEWAY_ADMIN_KEY_HASH", KEYS_SECRET, "admin-key-hash"),
    ])
    literal = json.dumps([
        {"name": "GATEWAY_RUNTIME_KEY_HASH", "value": "sha256:" + "b" * 64},
        secret_env("GATEWAY_ADMIN_KEY_HASH", KEYS_SECRET, "admin-key-hash"),
    ])
    duplicate = json.dumps(gateway_key_env(KEYS_SECRET) + [
        {"name": "GATEWAY_ADMIN_KEY_HASH", "value": "sha256:" + "c" * 64},
    ])
    return {
        "default-install": (),
        "keyless-minimal": ("--set", GATEWAY_DB_URL),
        "keyless-postgres": (*managed, "--set", "gateway.keysSecret="),
        "keyless-local": ("-f", "deploy/local/values.yaml", "--set", "gateway.keysSecret="),
        "no-hash-env": ("--set", GATEWAY_DB_URL, "--set", "gateway.keysSecret=" + KEYS_SECRET),
        "hash-from-other-secret": (*managed, "--set-json",
                                   "agentgateway-standalone.extraEnv=" + other_secret),
        "literal-hash": (*managed, "--set-json",
                         "agentgateway-standalone.extraEnv=" + literal),
        "duplicate-hash-env": (*managed, "--set-json",
                               "agentgateway-standalone.extraEnv=" + duplicate),
        "model-policy-removed": (*managed, "--set",
                                 "agentgateway-standalone.config.llm.policies=null"),
        "management-policy-open": (*managed, "--set",
                                   "agentgateway-standalone.config.ui.policies.apiKey.mode=optional"),
        "extra-model-key": (*managed, "--set-json",
                            'agentgateway-standalone.config.llm.policies.apiKey.keys='
                            '[{"keyHash":"${GATEWAY_RUNTIME_KEY_HASH}"},'
                            '{"keyHash":"sha256:' + "d" * 64 + '"}]'),
    }


def existing_keyless_arguments(files):
    """Existing-gateway installs: the managed key rules must not apply."""
    supplied = ("--set", "gateway.mode=existing", "--set", "gateway.install=false",
                "--set", "gateway.url=" + SUPPLIED_URL)
    return {
        "existing-no-keys-secret": supplied,
        "existing-gateway-values-without-policy": (
            "-f", str(files["existing"]),
            "--set", "agentgateway-standalone.config.llm.policies=null",
            "--set", "agentgateway-standalone.extraEnv=null",
        ),
    }


COPY_HOSTS = ("customer-gateway-0.customer-gateway.gateway.svc.cluster.local",
              "customer-gateway-1.customer-gateway.gateway.svc.cluster.local")
SUPPLIED_COPIES = [f"http://{host}:4000" for host in COPY_HOSTS]
BAD_COPY_URLS = {
    "credentials": "http://admin:secret@gateway-0.gateway:4000",
    "path": "http://gateway-0.gateway:4000/api",
    "query": "http://gateway-0.gateway:4000?x=1",
    "scheme": "ftp://gateway-0.gateway:4000",
    "space": "http://gateway 0:4000",
    "trailing-comma-join": "http://gateway-0.gateway:4000,http://gateway-1.gateway:4000",
}


def managed_copy_urls(release, count, namespace="default"):
    return ",".join(
        f"http://{release}-gateway-{index}.{release}-gateway-copies.{namespace}.svc:4000"
        for index in range(count)
    )


def copy_arguments(files):
    """Managed copy counts and supplied copy lists, good and bad."""
    managed = ("-f", str(files["managed"]))
    existing = ("-f", str(files["existing"]))
    arguments = {
        "managed-default": managed,
        "managed-three": (*managed, "--set", "gateway.copies=3",
                          "--set", "networkPolicy.gatewayIngressEnabled=true"),
        "managed-one": (*managed, "--set", "gateway.copies=1"),
        "managed-zero": (*managed, "--set", "gateway.copies=0"),
        "managed-too-many": (*managed, "--set", "gateway.copies=33"),
        "managed-bundled-replicas": (*managed, "--set",
                                     "agentgateway-standalone.replicaCount=2"),
        "managed-autoscaling": (*managed, "--set",
                                "agentgateway-standalone.autoscaling.enabled=true"),
        "managed-supplied-list": (*managed, "--set-json",
                                  "gateway.copyUrls=" + json.dumps(SUPPLIED_COPIES)),
        "existing-list": (*existing, "--set-json",
                          "gateway.copyUrls=" + json.dumps(SUPPLIED_COPIES)),
        "existing-https": (*existing, "--set-json",
                           'gateway.copyUrls=["https://10.0.0.7:8443"]'),
        "existing-duplicate": (*existing, "--set-json",
                               "gateway.copyUrls=" + json.dumps(SUPPLIED_COPIES[:1] * 2)),
        "existing-too-many": (*existing, "--set-json", "gateway.copyUrls=" + json.dumps(
            [f"http://gateway-{index}.gateway:4000" for index in range(33)])),
    }
    for label, url in BAD_COPY_URLS.items():
        arguments["existing-bad-" + label] = (
            *existing, "--set-json", "gateway.copyUrls=" + json.dumps([url]))
    return arguments


def app_variables(output, release="pg"):
    app = next(d for d in workloads(output) if name_of(d) == release + "-app")
    return {var: value for var, value, _ in env(containers(app)[0])}


def copy_cases(results):
    """SHAPE-10 and SHAPE-11: the app's gateway copy list."""
    rows = []
    managed = {}
    for label, count in (("managed-default", 2), ("managed-three", 3), ("managed-one", 1)):
        result = results[label]
        output = result.stdout
        copies = next((d for d in of_kind(output, "StatefulSet")
                       if name_of(d) == "pg-gateway"), "")
        headless = next((d for d in of_kind(output, "Service")
                         if name_of(d) == "pg-gateway-copies"), "")
        bundled = next((d for d in of_kind(output, "Deployment") if name_of(d) == "pg"), "")
        policy = "\n".join(of_kind(output, "NetworkPolicy"))
        policy_labels = labels(block(block(block(policy, "spec"), "podSelector"),
                                     "matchLabels"))
        copy_labels = pod_labels(copies) if copies else {}
        managed[label] = {
            "exit": result.returncode,
            "copy_urls": app_variables(output).get("GATEWAY_COPY_URLS")
            if result.returncode == 0 else None,
            "expected": managed_copy_urls("pg", count),
            "replicas": scalar(copies, "replicas"),
            "service_name": scalar(copies, "serviceName"),
            "headless_ports": sorted({scalar(p, "port") for p in
                                      items(block(block(headless, "spec"), "ports"))}),
            "headless": scalar(headless, "clusterIP") == "None",
            "bundled_replicas": scalar(bundled, "replicas"),
            "copy_labels": copy_labels,
            "policy_selects_copies": bool(policy_labels)
            and all(copy_labels.get(k) == v for k, v in policy_labels.items()),
        }
    refused_managed = {
        label: {"exit": results[label].returncode,
                "names_setting": any(name in results[label].stderr for name in
                                     ("gateway.copies", "copies", "copyUrls",
                                      "replicaCount", "autoscaling"))}
        for label in ("managed-zero", "managed-too-many", "managed-bundled-replicas",
                      "managed-autoscaling", "managed-supplied-list")
    }
    rows.append(case(
        "SHAPE-10",
        all(
            found["exit"] == 0
            and found["copy_urls"] == found["expected"]
            and found["replicas"] == str(len(found["expected"].split(",")))
            and found["service_name"] == "pg-gateway-copies"
            and found["headless"] and found["headless_ports"] == ["4000"]
            and found["bundled_replicas"] == "0"
            and found["copy_labels"].get("app.kubernetes.io/component") == "standalone"
            for found in managed.values()
        )
        and managed["managed-three"]["policy_selects_copies"]
        and all(found["exit"] != 0 and found["names_setting"]
                for found in refused_managed.values()),
        {"managed": managed, "refused": refused_managed},
    ))

    supplied = {
        label: {"exit": results[label].returncode,
                "copy_urls": app_variables(results[label].stdout).get("GATEWAY_COPY_URLS")
                if results[label].returncode == 0 else None,
                "gateway_rendered": "agentgateway-standalone" in results[label].stdout}
        for label in ("existing-list", "existing-https")
    }
    refused_supplied = {
        label: {"exit": result.returncode,
                "schema_names_list": "copyUrls" in result.stderr}
        for label, result in results.items()
        if label.startswith("existing-") and label not in supplied
    }
    rows.append(case(
        "SHAPE-11",
        supplied["existing-list"]["exit"] == 0
        and supplied["existing-list"]["copy_urls"] == ",".join(SUPPLIED_COPIES)
        and supplied["existing-https"]["exit"] == 0
        and supplied["existing-https"]["copy_urls"] == "https://10.0.0.7:8443"
        and not any(found["gateway_rendered"] for found in supplied.values())
        and len(refused_supplied) == len(BAD_COPY_URLS) + 2
        and all(found["exit"] != 0 and found["schema_names_list"]
                for found in refused_supplied.values()),
        {"supplied": supplied, "refused": refused_supplied},
    ))
    return rows


def gateway_env_refs(container):
    """Variable -> (Secret name, key) for secretKeyRef env entries."""
    found = {}
    for item in items(block(container, "env")):
        if "secretKeyRef:" in item:
            reference = "\n".join(block(item, "secretKeyRef"))
            found[scalar(item, "name")] = (scalar(reference, "name"), scalar(reference, "key"))
    return found


def key_policies(config):
    """Section -> (mode, key hashes) for the apiKey policies in a gateway ConfigMap."""
    lines = config.splitlines()
    found = {}
    for section in ("ui", "llm"):
        policy = block(block(block(lines, section), "policies"), "apiKey")
        text = "\n".join(policy)
        found[section] = (
            scalar(text, "mode"),
            [h.strip("\"'") for h in re.findall(r"keyHash: (\S+)", text)],
        )
    return found


def render(name, *args):
    result = run("template", name, CHART, *args)
    assert result.returncode == 0, result.stderr
    return result.stdout


def run_cases():
    with tempfile.TemporaryDirectory() as directory:
        files = {}
        for mode in ("managed", "existing"):
            files[mode] = Path(directory) / (mode + ".json")
            files[mode].write_text(json.dumps(postgres_values(mode)))
        renders = {
            "postgres-managed": render("pg", "-f", str(files["managed"])),
            "postgres-existing": render("pg", "-f", str(files["existing"])),
            "local-managed": render("keeplane", "-f", "deploy/local/values.yaml"),
            "local-existing": render(
                "keeplane-existing", "-f", "deploy/local/existing-values.yaml"
            ),
        }
        tagged = run(
            "template", "pg", CHART, "-f", str(files["managed"]), "--set",
            "agentgateway-standalone.image=cr.agentgateway.dev/agentgateway:v1.6.0",
        )
        mapped = run(
            "template", "pg", CHART, "-f", str(files["managed"]), "--set-json",
            'agentgateway-standalone.image={"registry":"cr.agentgateway.dev",'
            '"repository":"agentgateway","tag":"v1.6.0"}',
        )
        tagged_existing = run(
            "template", "pg", CHART, "-f", str(files["existing"]), "--set",
            "agentgateway-standalone.image=cr.agentgateway.dev/agentgateway:v1.6.0",
        )
        refusals = {
            label: run("template", "pg", CHART, *arguments)
            for label, arguments in key_refusal_arguments(files["managed"]).items()
        }
        existing_keyless = {
            label: run("template", "pg", CHART, *arguments)
            for label, arguments in existing_keyless_arguments(files).items()
        }
        copies = {
            label: run("template", "pg", CHART, *arguments)
            for label, arguments in copy_arguments(files).items()
        }
    managed, existing = renders["postgres-managed"], renders["postgres-existing"]
    managed_kinds = {"postgres-managed", "local-managed"}
    rows = []

    # SHAPE-01: images and the gateway chart dependency are pinned.
    chart_yaml = (ROOT / CHART / "Chart.yaml").read_text()
    dependency_versions = re.findall(r"^\s+version: (\S+)$", chart_yaml, re.M)
    lock_digest = scalar((ROOT / CHART / "Chart.lock").read_text(), "digest") or ""
    postgres_images = {name: images(renders[name])
                       for name in ("postgres-managed", "postgres-existing")}
    local_images = {
        name: [image for image in images(renders[name]) if image != "keeplane-preview:kind-local"]
        for name in ("local-managed", "local-existing")
    }
    refusal = "agentgateway-standalone.image pinned"
    rows.append(case(
        "SHAPE-01",
        set(postgres_images["postgres-managed"]) == {IMAGE, GATEWAY_IMAGE}
        and len(postgres_images["postgres-managed"]) >= 4
        and set(postgres_images["postgres-existing"]) == {IMAGE}
        and all(PINNED.fullmatch(image) for found in postgres_images.values() for image in found)
        # The gateway copies and the bundled zero-replica Deployment.
        and local_images["local-managed"] == [GATEWAY_IMAGE, GATEWAY_IMAGE]
        and local_images["local-existing"] == []
        and tagged.returncode != 0 and refusal in tagged.stderr
        and mapped.returncode != 0 and refusal in mapped.stderr
        and tagged_existing.returncode == 0
        and dependency_versions == [GATEWAY["chart"]["version"]]
        and re.fullmatch(r"v?\d+\.\d+\.\d+", dependency_versions[0]) is not None
        and re.fullmatch(r"sha256:[0-9a-f]{64}", lock_digest) is not None,
        {
            "postgres_images": {k: sorted(set(v)) for k, v in postgres_images.items()},
            "local_images_besides_trial_app_tag": local_images,
            "tagged_gateway_exit": tagged.returncode,
            "mapped_gateway_exit": mapped.returncode,
            "existing_mode_ignores_gateway_image_exit": tagged_existing.returncode,
            "gateway_chart_version": dependency_versions,
        },
    ))

    # SHAPE-02: private gateway listeners stay off Services, Ingress and pods' ports.
    exposure = {}
    for name, output in renders.items():
        services = {}
        for service in of_kind(output, "Service"):
            ports = items(block(block(service, "spec"), "ports"))
            services[name_of(service)] = {
                "type": scalar(service, "type"),
                "ports": sorted({scalar(p, "port") for p in ports}
                                | {scalar(p, "targetPort") for p in ports}),
                "selects_gateway": "app.kubernetes.io/name: agentgateway-standalone"
                in "\n".join(block(block(service, "spec"), "selector")),
                "headless": scalar(service, "clusterIP") == "None",
            }
        backends = sorted(set(re.findall(
            r"service:\s*\n\s+name: (\S+)\s*\n\s+port:\s*\n\s+number: (\d+)", output
        )))
        exposure[name] = {
            "services": services,
            "ingress_backends": backends,
            "container_ports": sorted(set(re.findall(r"containerPort: (\d+)", output))),
            "listener_overrides": sorted(set(re.findall(
                r"\b(adminAddr|statsAddr|readinessAddr):", output))),
        }
    release = {"postgres-managed": "pg", "postgres-existing": "pg",
               "local-managed": "keeplane", "local-existing": "keeplane-existing"}
    private_ok = all(
        not (PRIVATE_GATEWAY_PORTS & set(port for svc in seen["services"].values()
                                         for port in svc["ports"]))
        and not PRIVATE_GATEWAY_PORTS & set(seen["container_ports"])
        and not seen["listener_overrides"]
        and seen["services"][release[name] + "-app"]["ports"] == ["3000"]
        # Managed mode: the gateway Service plus the headless Service that
        # gives each copy its own address; both carry only port 4000.
        and {n: s for n, s in seen["services"].items() if s["selects_gateway"]}
        == ({release[name]: {"type": "ClusterIP", "ports": ["4000"],
                             "selects_gateway": True, "headless": False},
             release[name] + "-gateway-copies": {"type": "ClusterIP", "ports": ["4000"],
                                                 "selects_gateway": True, "headless": True}}
            if name in managed_kinds else {})
        and set(seen["services"]) == ({release[name], release[name] + "-app",
                                       release[name] + "-gateway-copies"}
                                      if name in managed_kinds else {release[name] + "-app"})
        for name, seen in exposure.items()
    )
    rows.append(case(
        "SHAPE-02",
        private_ok
        and all(exposure[name]["ingress_backends"] == [("pg-app", "3000")]
                for name in ("postgres-managed", "postgres-existing"))
        and all(exposure[name]["services"]["pg-app"]["type"] == "ClusterIP"
                for name in ("postgres-managed", "postgres-existing")),
        exposure,
    ))

    # SHAPE-03: the gateway NetworkPolicy admits only this release's app pods.
    policies = of_kind(managed, "NetworkPolicy")
    expected_spec = (
        "spec:\n"
        "  podSelector:\n"
        "    matchLabels:\n"
        "      app.kubernetes.io/name: agentgateway-standalone\n"
        "      app.kubernetes.io/instance: pg\n"
        "  policyTypes: [Ingress]\n"
        "  ingress:\n"
        "    - from:\n"
        "        - podSelector:\n"
        "            matchLabels:\n"
        "              app: pg-app\n"
        "      ports:\n"
        "        - protocol: TCP\n"
        "          port: 4000\n"
    )
    pods = {name_of(doc): pod_labels(doc) for doc in workloads(managed)}
    admitted = [name for name, found in pods.items() if found.get("app") == "pg-app"]
    # The serving copies: the policy must select every one of them.
    gateway_pods = pods.get("pg-gateway", {})
    rows.append(case(
        "SHAPE-03",
        len(policies) == 1
        and policies[0].rstrip("\n").endswith(expected_spec.rstrip("\n"))
        and "namespaceSelector" not in policies[0]
        and "ipBlock" not in policies[0]
        and gateway_pods.get("app.kubernetes.io/name") == "agentgateway-standalone"
        and gateway_pods.get("app.kubernetes.io/instance") == "pg"
        and admitted == ["pg-app"]
        and not of_kind(existing, "NetworkPolicy")
        and not of_kind(renders["local-managed"], "NetworkPolicy"),
        {"policies": len(policies), "pods_with_admitted_label": admitted,
         "pod_labels": pods},
    ))

    # SHAPE-04: credentials come from Secret objects the installer creates.
    secret_findings = {}
    for name, output in renders.items():
        problems = []
        if of_kind(output, "Secret"):
            problems.append("chart renders a Secret object")
        for doc in workloads(output):
            vols = volumes(doc)
            for container in containers(doc) + containers(doc, "initContainers"):
                mounted = {path: (volume, read_only)
                           for volume, path, read_only in mounts(container)}
                for variable, value, from_secret in env(container):
                    if not SENSITIVE.search(variable or ""):
                        continue
                    if value is None and not from_secret:
                        problems.append(variable + " has no Secret reference")
                    elif value is not None and not value.startswith("/"):
                        problems.append(variable + " carries a literal value")
                    elif value and variable.endswith("_FILE"):
                        directory = str(Path(value).parent)
                        volume, read_only = mounted.get(directory, (None, False))
                        if vols.get(volume, (None,))[0] != "secret" or not read_only:
                            problems.append(variable + " is not a read-only Secret file")
        for password in re.findall(r"://[^/\s:@\"]+:([^@\s\"]+)@", output):
            if not re.fullmatch(r"\$\{[A-Z_]+\}", password):
                problems.append("connection URL carries a literal password")
        if name in managed_kinds:
            config = "\n".join(of_kind(output, "ConfigMap"))
            placeholders = set(re.findall(r"\$\{([A-Z_]+)\}", config))
            hashes = [h.strip("\"'") for h in re.findall(r"keyHash: (\S+)", config)]
            # The serving copies and the bundled chart's zero-replica Deployment.
            for gateway_name in (release[name] + "-gateway", release[name]):
                gateway = next(d for d in workloads(output) if name_of(d) == gateway_name)
                refs = {var for var, _, secret in env(containers(gateway)[0]) if secret}
                if not placeholders or not placeholders <= refs:
                    problems.append(gateway_name + " placeholders lack Secret-backed variables")
            if len(hashes) != 2 or not all(re.fullmatch(r"\$\{[A-Z_]+\}", h) for h in hashes):
                problems.append("gateway key policies are not placeholders")
        secret_findings[name] = problems
    rows.append(case(
        "SHAPE-04",
        not any(secret_findings.values())
        and "KEEPLANE_DB_PASSWORD" not in existing
        and "KEEPLANE_DB_PASSWORD" not in renders["local-existing"],
        {"problems": secret_findings},
    ))

    # SHAPE-05: long-running containers report readiness; state sits on claims.
    shape = {}
    for name, output in renders.items():
        problems, state = [], []
        for doc in of_kind(output, "Deployment") + of_kind(output, "StatefulSet"):
            vols = volumes(doc)
            for container in containers(doc):
                label = name_of(doc) + "/" + scalar(container, "name")
                if "readinessProbe:" not in container:
                    problems.append(label + " has no readiness probe")
                if "readOnlyRootFilesystem: true" not in container:
                    problems.append(label + " can write its root filesystem")
                for volume, path, read_only in mounts(container):
                    kind, claim = vols.get(volume, (None, None))
                    if read_only:
                        continue
                    if kind == "persistentVolumeClaim":
                        state.append(label + ":" + path + "=" + claim)
                    elif not (kind == "emptyDir" and path == "/tmp"):
                        problems.append(label + " writes " + path + " on " + str(kind))
        declared = {name_of(doc) for doc in of_kind(output, "PersistentVolumeClaim")}
        shape[name] = {"problems": problems, "writable_state": sorted(state),
                       "declared_claims": sorted(declared)}
    app_container = containers(next(d for d in workloads(managed) if name_of(d) == "pg-app"))[0]
    gateway_container = containers(
        next(d for d in workloads(managed) if name_of(d) == "pg-gateway"))[0]
    gateway_config = "\n".join(of_kind(managed, "ConfigMap"))
    jobs = of_kind(managed, "Job") + of_kind(existing, "Job")
    rows.append(case(
        "SHAPE-05",
        not any(found["problems"] for found in shape.values())
        and shape["postgres-managed"]["writable_state"]
        == ["pg-app/app:/provider-keys=keeplane-provider-keys"]
        and shape["postgres-existing"]["writable_state"]
        == ["pg-app/app:/provider-keys=keeplane-provider-keys"]
        and shape["postgres-managed"]["declared_claims"] == []
        and shape["local-managed"]["declared_claims"]
        == ["keeplane-provider-keys", "keeplane-state"]
        and shape["local-existing"]["declared_claims"]
        == ["keeplane-existing-provider-keys", "keeplane-existing-state"]
        and {"keeplane-app/app:/state=keeplane-state",
             "keeplane-app/app:/provider-keys=keeplane-provider-keys"}
        <= set(shape["local-managed"]["writable_state"])
        and "path: /health/ready" in "\n".join(block(app_container, "readinessProbe"))
        and "path: /health/app" in "\n".join(block(app_container, "livenessProbe"))
        and "path: /healthz/ready" in "\n".join(block(gateway_container, "readinessProbe"))
        and "startupProbe:" in gateway_container
        and "mode: hybrid" in gateway_config
        and "replicas: 2" in next(d for d in workloads(managed) if name_of(d) == "pg-gateway")
        and "replicas: 0" in next(d for d in workloads(managed) if name_of(d) == "pg")
        and "replicas: 2" in next(d for d in workloads(managed) if name_of(d) == "pg-app")
        and len(jobs) == 3
        and all("backoffLimit: 0" in job and "activeDeadlineSeconds:" in job
                and "pre-install,pre-upgrade" in job for job in jobs),
        shape,
    ))

    # SHAPE-06: existing-gateway mode installs nothing of a gateway's own.
    supplied = {}
    for name in ("postgres-existing", "local-existing"):
        output = renders[name]
        app = next(d for d in workloads(output) if name_of(d) == release[name] + "-app")
        variables = {var: value for var, value, _ in env(containers(app)[0])}
        supplied[name] = {
            "kinds": sorted({kind_of(doc) for doc in manifests(output)}),
            "deployments": sorted(name_of(d) for d in of_kind(output, "Deployment")),
            "gateway_source_rendered": "charts/agentgateway-standalone/" in output,
            "gateway_labels_rendered": "agentgateway-standalone" in output,
            "unrelated_model_rendered": UNRELATED_MODEL in output,
            "gateway_url": variables.get("GATEWAY_URL"),
            "gateway_mode": variables.get("GATEWAY_MODE"),
            "file_config": "GATEWAY_FILE_CONFIG" in variables,
            "copy_urls": variables.get("GATEWAY_COPY_URLS"),
        }
    rows.append(case(
        "SHAPE-06",
        all(
            set(found["kinds"]) <= {"Deployment", "Service", "Job", "Ingress",
                                    "PersistentVolumeClaim"}
            and found["deployments"] == [release[name] + "-app"]
            and not found["gateway_source_rendered"]
            and not found["gateway_labels_rendered"]
            and not found["unrelated_model_rendered"]
            and found["gateway_mode"] == "existing"
            and not found["file_config"]
            and found["copy_urls"] is None
            for name, found in supplied.items()
        )
        and supplied["postgres-existing"]["gateway_url"] == SUPPLIED_URL
        and UNRELATED_MODEL in managed,
        supplied,
    ))

    # SHAPE-07: the chart itself closes the managed gateway with gateway.keysSecret.
    wiring = {}
    for name in sorted(managed_kinds):
        output = renders[name]
        gateway = next(d for d in workloads(output) if name_of(d) == release[name] + "-gateway")
        config = "\n".join(of_kind(output, "ConfigMap"))
        wiring[name] = {
            "policies": key_policies(config),
            "hash_env": {
                variable: reference
                for variable, reference in gateway_env_refs(containers(gateway)[0]).items()
                if variable.endswith("_KEY_HASH")
            },
            "secret_objects": len(of_kind(output, "Secret")),
            # Image digests (`@sha256:`) are allowed; a key hash is not.
            "literal_hashes": len(re.findall(r"(?<!@)sha256:[0-9a-f]{64}", output)),
        }
    rows.append(case(
        "SHAPE-07",
        all(
            found["policies"] == {
                "ui": ("strict", ["${GATEWAY_ADMIN_KEY_HASH}"]),
                "llm": ("strict", ["${GATEWAY_RUNTIME_KEY_HASH}"]),
            }
            and found["hash_env"] == {
                "GATEWAY_RUNTIME_KEY_HASH": (KEYS_SECRET, "runtime-key-hash"),
                "GATEWAY_ADMIN_KEY_HASH": (KEYS_SECRET, "admin-key-hash"),
            }
            and found["secret_objects"] == 0
            and found["literal_hashes"] == 0
            for found in wiring.values()
        )
        and "policies" not in json.dumps(gateway_values())
        and "policies:" not in (ROOT / "deploy/local/values.yaml").read_text(),
        wiring,
    ))

    # SHAPE-08: Helm refuses a managed gateway that would not check keys.
    refused = {
        label: {
            "exit": result.returncode,
            "names_keys_secret": "gateway.keysSecret" in result.stderr,
            "says_create_secret": KEYS_MESSAGE in result.stderr,
            "names_policy": "key policy must stay strict" in result.stderr,
        }
        for label, result in refusals.items()
    }
    keyless = ("default-install", "keyless-minimal", "keyless-postgres", "keyless-local")
    unwired = ("no-hash-env", "hash-from-other-secret", "literal-hash", "duplicate-hash-env")
    opened = ("model-policy-removed", "management-policy-open", "extra-model-key")
    rows.append(case(
        "SHAPE-08",
        all(found["exit"] != 0 for found in refused.values())
        and all(refused[label]["says_create_secret"] for label in keyless)
        and all(refused[label]["names_keys_secret"] for label in keyless + unwired)
        and all(refused[label]["names_policy"] for label in opened)
        and all(KEYS_SECRET not in result.stdout for result in refusals.values()),
        refused,
    ))

    # SHAPE-09: existing-gateway mode needs none of the managed gateway's key rules.
    supplied_keyless = {
        label: {
            "exit": result.returncode,
            "gateway_rendered": "agentgateway-standalone" in result.stdout,
            "keys_message": KEYS_MESSAGE in result.stderr,
        }
        for label, result in existing_keyless.items()
    }
    rows.append(case(
        "SHAPE-09",
        all(found["exit"] == 0 and not found["gateway_rendered"]
            and not found["keys_message"] for found in supplied_keyless.values()),
        supplied_keyless,
    ))

    rows.extend(copy_cases(copies))

    report = {"suite": "Keeplane chart installation shape", "results": rows,
              "release_package_approved": False}
    print(json.dumps(report, indent=2))
    return int(any(row["verdict"] != "pass" for row in rows))


if __name__ == "__main__":
    sys.exit(run_cases())


def test_chart_installation_shape(report_file, capsys):
    assert run_cases() in (None, 0)
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    verify_cases(__file__, output.out, report_file)
