"""Run the plain-English K8S cases against the isolated local kind cluster.

This test deletes one gateway pod. It refuses any kubeconfig without the exact
kind-keeplane context so it cannot touch an unrelated Kubernetes cluster.
"""

import json
import os
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from protected_preview import login_if_protected


KUBECONFIG = os.environ.get("KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig")
BASE = os.environ.get("KEEPLANE_BASE_URL", "http://127.0.0.1:13000")


def kubectl(*args):
    return subprocess.check_output(
        ["kubectl", "--kubeconfig", KUBECONFIG, *args], text=True
    ).strip()


def ask(base=BASE):
    request = Request(
        base + "/api/ask",
        data=json.dumps({"model": "second-local", "prompt": "fixture"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def register_existing():
    request = Request(
        BASE + "/api/models",
        data=json.dumps({"name": "second-local", "source": "fixture", "model": "mock-local"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def direct_catalog(namespace, app, url):
    probe = '''import json,pathlib,sys,urllib.error,urllib.request
url=sys.argv[1]+"/v1/models"
try:
 urllib.request.urlopen(url,timeout=10)
 anonymous=200
except urllib.error.HTTPError as error:
 anonymous=error.code
key=pathlib.Path("/run/gateway-keys/runtime-key").read_text().strip()
request=urllib.request.Request(url,headers={"Authorization":"Bearer "+key})
with urllib.request.urlopen(request,timeout=15) as response:
 models=[item["id"] for item in json.load(response)["data"]]
print(json.dumps({"anonymous":anonymous,"models":models}))'''
    return json.loads(kubectl("-n", namespace, "exec", "deploy/" + app, "--",
                              "python", "-c", probe, url))


def main():
    context = kubectl("config", "current-context")
    if context != "kind-keeplane":
        raise SystemExit(f"Refusing Kubernetes context {context!r}; expected kind-keeplane")
    login_if_protected(BASE)
    # The protected app requires a reviewed model setup before model calls.
    with urlopen(BASE + "/api/models", timeout=15) as response:
        catalog = json.load(response)["models"]
    second = next((model for model in catalog if model["id"] == "second-local"), None)
    if second and not second["approved"]:
        setup = Request(BASE + "/api/models/second-local/setup", method="POST",
                        data=json.dumps({"key_choice": "none", "approved_classes": []}).encode(),
                        headers={"Content-Type": "application/json"})
        with urlopen(setup, timeout=45) as response:
            if response.status != 200:
                raise RuntimeError("Could not set up the gateway failover fixture")

    results = []

    def check(case, okay, observed):
        results.append({"case": case, "verdict": "pass" if okay else "fail", "observed": observed})

    pods = json.loads(kubectl("-n", "keeplane", "get", "pods", "-l",
                              "app.kubernetes.io/component=standalone", "-o", "json"))["items"]
    ready = [p for p in pods if p["status"].get("phase") == "Running" and
             any(c.get("type") == "Ready" and c.get("status") == "True"
                 for c in p["status"].get("conditions", []))]
    check("K8S-01", len(ready) == 2, {"ready_replicas": len(ready)})
    if len(ready) != 2:
        print(json.dumps({"suite": "Keeplane local Kubernetes", "results": results}, indent=2))
        return 1

    direct = []
    for pod in ready:
        ip = pod["status"]["podIP"]
        body = direct_catalog("keeplane", "keeplane-app", f"http://{ip}:4000")
        direct.append({"pod": pod["metadata"]["name"],
                       **body})
    check("K8S-02", all(entry["anonymous"] == 401 and "second-local" in entry["models"]
                         for entry in direct), direct)

    removed = ready[0]["metadata"]["name"]
    kubectl("-n", "keeplane", "delete", "pod", removed, "--wait=false")
    # Calls already aimed at a terminating pod may reset. Wait until the
    # Service no longer offers it as a ready endpoint before checking new calls.
    endpoint_deadline = time.monotonic() + 30
    while True:
        slices = json.loads(kubectl("-n", "keeplane", "get", "endpointslice", "-l",
                                    "kubernetes.io/service-name=keeplane", "-o", "json"))["items"]
        endpoints = [endpoint for item in slices for endpoint in item.get("endpoints", [])]
        removed_ready = any(endpoint.get("targetRef", {}).get("name") == removed and
                            endpoint.get("conditions", {}).get("ready") is True
                            for endpoint in endpoints)
        survivor_ready = any(endpoint.get("targetRef", {}).get("name") != removed and
                             endpoint.get("conditions", {}).get("ready") is True
                             for endpoint in endpoints)
        if not removed_ready and survivor_ready:
            break
        if time.monotonic() >= endpoint_deadline:
            raise RuntimeError("Gateway Service did not remove the stopped pod")
        time.sleep(0.2)
    responses = []
    for _ in range(10):
        try:
            status, body = ask()
            responses.append({"status": status, "answer": body.get("answer"),
                              "error": body.get("error"), "detail": body.get("detail")})
        except Exception as error:
            responses.append({"error": str(error)})
        time.sleep(0.2)
    check("K8S-03", all(r.get("status") == 200 and r.get("answer") == "mock answer"
                        for r in responses), {"removed_pod": removed,
                                             "service_removed_stopped_endpoint": True,
                                             "calls": responses})

    subprocess.check_call(["kubectl", "--kubeconfig", KUBECONFIG, "-n", "keeplane",
                           "rollout", "status", "deployment/keeplane", "--timeout=120s"],
                          stdout=subprocess.DEVNULL)
    replacement = json.loads(kubectl("-n", "keeplane", "get", "deployment", "keeplane", "-o", "json"))
    check("K8S-04", replacement["status"].get("readyReplicas") == 2,
          {"ready_replicas": replacement["status"].get("readyReplicas")})

    registrations = []
    for _ in range(5):
        try:
            status, body = register_existing()
            registrations.append({"status": status, "existing": body.get("existing"),
                                  "error": body.get("error")})
        except Exception as error:
            registrations.append({"error": str(error)})
    check("K8S-07", all(r.get("status") == 200 and r.get("existing") is True
                        for r in registrations), registrations)

    resources = json.loads(kubectl("-n", "keeplane-existing", "get", "deploy,svc,pvc", "-o", "json"))["items"]
    names = sorted((r["kind"], r["metadata"]["name"]) for r in resources)
    registration = kubectl("-n", "keeplane-existing", "exec", "deploy/keeplane-existing-app", "--",
                           "python", "-c", "import json,urllib.request;u='http://localhost:3000';h={'Content-Type':'application/json'};b=json.dumps({'name':'customer-managed','source':'fixture','model':'mock-local'}).encode();r=urllib.request.Request(u+'/api/models',data=b,headers=h);print(urllib.request.urlopen(r,timeout=45).read().decode())")
    answer = kubectl("-n", "keeplane-existing", "exec", "deploy/keeplane-existing-app", "--",
                     "python", "-c", "import json,urllib.request;d=json.dumps({'model':'customer-managed','prompt':'fixture'}).encode();r=urllib.request.Request('http://localhost:3000/api/ask',data=d,headers={'Content-Type':'application/json'});print(urllib.request.urlopen(r,timeout=45).read().decode())")
    existing_deployment = json.loads(kubectl("-n", "keeplane-existing", "get", "deployment",
                                             "keeplane-existing-app", "-o", "json"))
    gateway_url = next((env["value"] for env in existing_deployment["spec"]["template"]["spec"]["containers"][0]["env"]
                        if env["name"] == "GATEWAY_URL"), "")
    check("K8S-05", names == [("Deployment", "keeplane-existing-app"),
                              ("Service", "keeplane-existing-app")] and
          gateway_url == "http://supplied-gateway.supplied-gateway.svc.cluster.local:4000" and
          json.loads(registration).get("name") == "customer-managed" and
          json.loads(answer).get("answer") == "mock answer",
          {"resources": names, "gateway_url": gateway_url,
           "registration": json.loads(registration), "answer": json.loads(answer).get("answer")})

    supplied_probe = direct_catalog("keeplane-existing", "keeplane-existing-app",
                                    "http://supplied-gateway.supplied-gateway.svc.cluster.local:4000")
    managed_probe = direct_catalog("keeplane-existing", "keeplane-existing-app",
                                   "http://keeplane.keeplane.svc.cluster.local:4000")
    supplied, managed = supplied_probe["models"], managed_probe["models"]
    customer_deployment = json.loads(kubectl("-n", "supplied-gateway", "get", "deployment",
                                             "supplied-gateway", "-o", "json"))
    separate = (customer_deployment["status"].get("readyReplicas") == 1
                and supplied_probe["anonymous"] == 401 and managed_probe["anonymous"] == 401
                and "customer-fixture" in supplied and "customer-fixture" not in managed
                and "customer-managed" in supplied and "customer-managed" not in managed
                and "second-local" in managed and "second-local" not in supplied)
    check("K8S-06", separate, {"supplied_models": supplied, "managed_models": managed,
                               "supplied_ready_replicas": customer_deployment["status"].get("readyReplicas")})

    print(json.dumps({"suite": "Keeplane local Kubernetes", "results": results}, indent=2))
    return 1 if any(r["verdict"] == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
