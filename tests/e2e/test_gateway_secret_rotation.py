"""Exercise Secret delivery, rotation and database recovery on isolated kind."""

import pytest

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import uuid

from tests.support.gateway_database_fixture import database_secret
from tests.support.helm import require_helm


ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = os.environ.get(
    "KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig"
)
HELM = require_helm()
NAMESPACE = "keeplane-db-" + uuid.uuid4().hex[:8]
RELEASE = "db-trial"
MODEL = "saved-before-rotation"
KEYS_SECRET = "keeplane-gateway-keys"
KEYS = {"runtime": secrets.token_urlsafe(32), "admin": secrets.token_urlsafe(32)}


def run(*command, input_text=None, check=True, timeout=180):
    result = subprocess.run(
        command,
        cwd=ROOT,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and result.returncode:
        # Kubernetes errors can echo a Secret manifest. Never record command I/O.
        raise RuntimeError(command[0] + " failed (exit " + str(result.returncode) + ")")
    return result


def kube(*args, **kwargs):
    return run("kubectl", "--kubeconfig", KUBECONFIG, "-n", NAMESPACE, *args, **kwargs)


def pods():
    return json.loads(
        kube(
            "get", "pods", "-l", "app.kubernetes.io/instance=" + RELEASE, "-o", "json"
        ).stdout
    )["items"]


def ready(pod):
    return not pod["metadata"].get("deletionTimestamp") and any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in pod["status"].get("conditions", [])
    )


def wait_for(check, timeout=60):
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise RuntimeError("Local database trial did not reach its expected state")
        time.sleep(0.5)


def rollout(name):
    kube("rollout", "status", "deployment/" + name, "--timeout=150s")


def keys_secret():
    """The installer-created key Secret the chart requires for its gateway."""
    data = {}
    for role, key in KEYS.items():
        data[role + "-key"] = key
        data[role + "-key-hash"] = "sha256:" + hashlib.sha256(key.encode()).hexdigest()
    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": KEYS_SECRET, "namespace": NAMESPACE},
        "type": "Opaque",
        "data": {
            name: base64.b64encode(value.encode()).decode()
            for name, value in data.items()
        },
    }
    kube("apply", "-f", "-", input_text=json.dumps(manifest))


def key_env(role):
    name = "GATEWAY_" + role.upper() + "_KEY_HASH"
    reference = {"name": KEYS_SECRET, "key": role + "-key-hash"}
    return {"name": name, "valueFrom": {"secretKeyRef": reference}}


def request(url, path, body=None, method=None, role="runtime"):
    # The key goes through stdin so it never appears in a process argument.
    probe = """import json,sys,urllib.request
url,path,body,method=sys.argv[1:]
key=sys.stdin.readline().strip()
data=None if body=="null" else body.encode()
request=urllib.request.Request(url+path,data=data,method=method or None,
 headers={"Content-Type":"application/json","Authorization":"Bearer "+key})
with urllib.request.urlopen(request,timeout=10) as response:
 print(json.dumps({"status":response.status,"body":json.load(response)}))"""
    result = kube(
        "exec",
        "-i",
        "deployment/model",
        "--",
        "python",
        "-c",
        probe,
        url,
        path,
        json.dumps(body),
        method or "",
        input_text=KEYS[role] + "\n",
    )
    return json.loads(result.stdout)


def snapshots():
    rows = []
    for pod in pods():
        if not ready(pod):
            continue
        url = "http://" + pod["status"]["podIP"] + ":4000"
        catalog = request(url, "/v1/models")
        answer = request(
            url,
            "/v1/chat/completions",
            {"model": MODEL, "messages": [{"role": "user", "content": "fixture"}]},
        )
        rows.append(
            {
                "pod_uid": pod["metadata"]["uid"],
                "model_present": MODEL
                in [item["id"] for item in catalog["body"]["data"]],
                "answer": answer["body"]["choices"][0]["message"]["content"],
            }
        )
    return rows


def model_works(rows):
    return len(rows) == 2 and all(
        row["model_present"] and row["answer"] == "mock answer" for row in rows
    )


def converged_models():
    try:
        rows = snapshots()
        return rows if model_works(rows) else None
    except RuntimeError:
        return None


def database_login(password):
    command = (
        "IFS= read -r PGPASSWORD; export PGPASSWORD; "
        'exec psql -w -h postgres -U keeplane -d keeplane -Atc "SELECT 1"'
    )
    return (
        kube(
            "exec",
            "-i",
            "deployment/postgres",
            "--",
            "sh",
            "-c",
            command,
            input_text=password + "\n",
            check=False,
        ).returncode
        == 0
    )


def run_cases():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Evidence output already exists")
    context = run(
        "kubectl", "--kubeconfig", KUBECONFIG, "config", "current-context"
    ).stdout.strip()
    if context != "kind-keeplane":
        raise RuntimeError("Refusing a Kubernetes context other than kind-keeplane")
    rows = []
    created = removed = False

    def record(identifier, passed, observed):
        rows.append(
            {
                "case": identifier,
                "verdict": "pass" if passed else "fail",
                "observed": observed,
            }
        )

    try:
        run("kubectl", "--kubeconfig", KUBECONFIG, "create", "namespace", NAMESPACE)
        created = True
        kube(
            "create",
            "configmap",
            "model-fixture",
            "--from-file=mock_model.py=tests/fixtures/mock_model.py",
        )
        kube("apply", "-f", "deploy/local/model-fixture.yaml")
        kube("apply", "-f", "deploy/local/postgres-fixture.yaml")
        keys_secret()
        with tempfile.TemporaryDirectory(prefix="keeplane-db-values-") as temporary:
            values = Path(temporary) / "values.json"
            values.write_text(
                json.dumps(
                    {
                        "app": {
                            "image": "keeplane-preview:kind-local",
                            "pullPolicy": "Never",
                        },
                        "gateway": {"keysSecret": KEYS_SECRET},
                        "agentgateway-standalone": {
                            "database": {
                                "postgres": {
                                    "url": "postgresql://keeplane:${KEEPLANE_DB_PASSWORD}@postgres:5432/keeplane"
                                }
                            },
                            "extraEnv": [
                                {
                                    "name": "KEEPLANE_DB_PASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "keeplane-gateway-db",
                                            "key": "password",
                                        }
                                    },
                                },
                                key_env("runtime"),
                                key_env("admin"),
                            ],
                        },
                    }
                )
            )
            run(
                HELM,
                "--kubeconfig",
                KUBECONFIG,
                "install",
                RELEASE,
                "deploy/helm/keeplane",
                "--namespace",
                NAMESPACE,
                "-f",
                str(values),
            )

        def missing_secret_pods():
            blocked = [
                pod
                for pod in pods()
                if any(
                    item.get("state", {}).get("waiting", {}).get("reason")
                    == "CreateContainerConfigError"
                    for item in pod["status"].get("containerStatuses", [])
                )
            ]
            return blocked if len(blocked) == 2 else None

        waiting = wait_for(missing_secret_pods)
        record(
            "GSECRET-05",
            len(waiting) == 2 and not any(ready(pod) for pod in pods()),
            {
                "missing_secret_blocks_pods": len(waiting),
                "ready_replicas": sum(ready(pod) for pod in pods()),
            },
        )
        original_password = database_secret(KUBECONFIG, NAMESPACE)
        rollout("postgres")
        rollout("model")
        rollout(RELEASE)
        config = json.loads(
            kube("get", "configmap", RELEASE + "-config", "-o", "json").stdout
        )
        manifest = run(
            HELM,
            "--kubeconfig",
            KUBECONFIG,
            "get",
            "manifest",
            RELEASE,
            "--namespace",
            NAMESPACE,
        ).stdout
        config_text = json.dumps(config["data"])
        secret_free = (
            original_password not in config_text and original_password not in manifest
        )
        record(
            "GSECRET-06",
            sum(ready(pod) for pod in pods()) == 2
            and secret_free
            and "${KEEPLANE_DB_PASSWORD}" in config_text
            and "secretKeyRef:" in manifest,
            {
                "ready_replicas": sum(ready(pod) for pod in pods()),
                "password_absent_from_config_and_helm": secret_free,
            },
        )
        resource = {
            "name": MODEL,
            "provider": {"custom": {"formats": [{"type": "completions"}]}},
            "params": {"model": "mock-local", "baseUrl": "http://model:18080/v1"},
        }
        saved = request(
            "http://" + RELEASE + ":4000",
            "/api/config/resources/llm.model",
            {"resources": [{"value": resource}]},
            "PUT",
            role="admin",
        )
        before = wait_for(converged_models)
        record(
            "GSECRET-07",
            saved["status"] == 200 and model_works(before),
            {"replicas": before},
        )
        replacement_password = secrets.token_urlsafe(32)
        kube(
            "exec",
            "-i",
            "deployment/postgres",
            "--",
            "psql",
            "-U",
            "keeplane",
            "-d",
            "keeplane",
            "-v",
            "ON_ERROR_STOP=1",
            input_text="ALTER ROLE keeplane PASSWORD '" + replacement_password + "';\n",
        )
        database_secret(KUBECONFIG, NAMESPACE, replacement_password)
        kube("rollout", "restart", "deployment/" + RELEASE)
        rollout(RELEASE)
        after = wait_for(converged_models)
        replaced = not {row["pod_uid"] for row in before} & {
            row["pod_uid"] for row in after
        }
        old_refused, new_accepted = (
            not database_login(original_password),
            database_login(replacement_password),
        )
        record(
            "GSECRET-08",
            replaced and old_refused and new_accepted and model_works(after),
            {
                "all_pods_replaced": replaced,
                "old_password_refused": old_refused,
                "new_password_accepted": new_accepted,
                "replicas": after,
            },
        )
        kube("scale", "deployment/" + RELEASE, "--replicas=0")
        wait_for(lambda: not pods())
        backup = kube(
            "exec",
            "deployment/postgres",
            "--",
            "pg_dump",
            "-U",
            "keeplane",
            "-d",
            "keeplane",
            "--clean",
            "--if-exists",
        ).stdout
        previous_db = json.loads(
            kube("get", "pods", "-l", "app=postgres", "-o", "json").stdout
        )["items"][0]["metadata"]["uid"]
        kube("rollout", "restart", "deployment/postgres")
        rollout("postgres")
        kube(
            "exec",
            "-i",
            "deployment/postgres",
            "--",
            "psql",
            "-U",
            "keeplane",
            "-d",
            "keeplane",
            "-v",
            "ON_ERROR_STOP=1",
            input_text=backup,
        )
        new_db = json.loads(
            kube("get", "pods", "-l", "app=postgres", "-o", "json").stdout
        )["items"][0]["metadata"]["uid"]
        kube("scale", "deployment/" + RELEASE, "--replicas=2")
        rollout(RELEASE)
        recovered = wait_for(converged_models)
        record(
            "GSECRET-09",
            previous_db != new_db
            and model_works(recovered)
            and database_login(replacement_password),
            {"database_pod_replaced": previous_db != new_db, "replicas": recovered},
        )
    except Exception as error:
        rows.append(
            {
                "case": "GSECRET-TRIAL",
                "verdict": "fail",
                "observed": {"error": type(error).__name__, "detail": str(error)[:160]},
            }
        )
    finally:
        if created:
            removed = (
                kube(
                    "delete", "namespace", NAMESPACE, "--wait=true", check=False
                ).returncode
                == 0
            )
    report = {
        "suite": "gateway database Secret rotation and recovery",
        "context": context,
        "results": rows,
        "namespace_removed": removed,
        "release_package_approved": False,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(
        len(rows) != 5 or not removed or any(row["verdict"] != "pass" for row in rows)
    )


if __name__ == "__main__":
    sys.exit(run_cases())


def test_gateway_secret_rotation(monkeypatch, report_file, request, capsys):
    arguments = [__file__, "--output", str(report_file)]
    monkeypatch.setattr("sys.argv", arguments)
    assert run_cases() in (None, 0)
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    verify_cases(__file__, output.out, globals().get("REPORT", report_file))


pytestmark = [pytest.mark.kubernetes]
