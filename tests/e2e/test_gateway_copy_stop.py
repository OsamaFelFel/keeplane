"""Stop one managed gateway copy in kind mid-stream and during admin changes.

Spec 002 ST4 "One gateway copy stops": a reply already streaming from the
stopped copy fails visibly and the same request, retried, is answered by the
surviving copy (K8S-18). While the copy is down, withdrawing access is saved at
once (K8S-19) and adding or widening access is refused with the admin's
copy-readback message (K8S-20); once the copy is back the add works (K8S-21).
The plain-English cases are in kubernetes-cases.md.

The copy is stopped by scaling the managed gateway StatefulSet down by one and
force-deleting that pod, so it cannot drain the stream and no replacement
starts until the test scales it back. The test refuses any kubeconfig without
the exact kind-keeplane context and always scales the copies back.
"""

import pytest

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from model_registry.copy_messages import not_added, not_changed, removed_but_listed
from tests.fixtures.mock_model import SLOW_STREAM_MARKER, slow_stream_text
from tests.support.client import Browser, RUNTIME
from tests.support.kind_trial import kind_kubeconfig


KUBECONFIG = kind_kubeconfig()
BASE = os.environ.get("KEEPLANE_BASE_URL", "http://127.0.0.1:13000")
NAMESPACE = "keeplane"
COPIES = "keeplane-gateway"
APP = "deploy/keeplane-app"
SERVICE_HOST = "keeplane.keeplane.svc.cluster.local"
PROBE = Path(__file__).resolve().parents[1] / "support/stream_probe.py"
SUFFIX = str(os.getpid())
WITHDRAW = "copy-stop-narrow-" + SUFFIX
REMOVE = "copy-stop-remove-" + SUFFIX
ADD = "copy-stop-add-" + SUFFIX
PROMPT = SLOW_STREAM_MARKER + ": stream slowly"


def kubectl(*args):
    return subprocess.check_output(
        ["kubectl", "--kubeconfig", KUBECONFIG, "-n", NAMESPACE, *args], text=True
    ).strip()


def copy_count():
    """The number of copies the app reads back (GATEWAY_COPY_URLS)."""
    deployment = json.loads(kubectl("get", APP, "-o", "json"))
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    urls = next(item["value"] for item in env if item["name"] == "GATEWAY_COPY_URLS")
    return len([url for url in urls.split(",") if url.strip()])


def copy_pods():
    pods = json.loads(
        kubectl(
            "get", "pods", "-l", "app.kubernetes.io/component=standalone", "-o", "json"
        )
    )["items"]
    return {
        pod["metadata"]["name"]: pod
        for pod in pods
        if pod["metadata"]["name"].startswith(COPIES + "-")
    }


def is_ready(pod):
    return pod["status"].get("phase") == "Running" and any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in pod["status"].get("conditions", [])
    )


def ready_endpoints():
    slices = json.loads(
        kubectl(
            "get",
            "endpointslice",
            "-l",
            "kubernetes.io/service-name=keeplane",
            "-o",
            "json",
        )
    )["items"]
    return sorted(
        endpoint.get("targetRef", {}).get("name", "")
        for item in slices
        for endpoint in item.get("endpoints", [])
        if endpoint.get("conditions", {}).get("ready") is True
    )


def start_probe(host, model):
    """Run stream_probe.py in the app pod; its JSON lines arrive on a queue."""
    process = subprocess.Popen(
        [
            "kubectl",
            "--kubeconfig",
            KUBECONFIG,
            "-n",
            NAMESPACE,
            "exec",
            "-i",
            APP,
            "--",
            "python",
            "-u",
            "-",
            host,
            "4000",
            model,
            PROMPT,
        ],
        stdin=PROBE.open(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    events = queue.Queue()

    def pump():
        for line in process.stdout:
            try:
                events.put(json.loads(line))
            except ValueError:
                events.put({"event": "output", "line": line[:200]})
        events.put(None)

    threading.Thread(target=pump, daemon=True).start()
    return process, events


def collect(events, until, deadline):
    """Read probe events until `until(chunks, end)` holds or time runs out."""
    chunks, end = [], None
    while not until(chunks, end):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            event = events.get(timeout=remaining)
        except queue.Empty:
            break
        if event is None:
            break
        if event.get("event") == "chunk":
            chunks.append(event["content"])
        elif event.get("event") == "end":
            end = event
    return chunks, end


def stop_probe(process):
    """Kill a probe that is still running, so no kubectl exec outlives the test."""
    if process is not None and process.poll() is None:
        process.kill()
        process.wait(timeout=10)


def stream_once(host, model, timeout=90):
    process, events = start_probe(host, model)
    try:
        _, end = collect(
            events, lambda c, e: e is not None, time.monotonic() + timeout
        )
        process.wait(timeout=30)
    finally:
        stop_probe(process)
    return end


COPY_MODELS = """import json,pathlib,sys,urllib.request
key=pathlib.Path("/run/gateway-keys/runtime-key").read_text().strip()
request=urllib.request.Request(sys.argv[1]+"/v1/models",headers={"Authorization":"Bearer "+key})
with urllib.request.urlopen(request,timeout=15) as response:
 print(json.dumps([item["id"] for item in json.load(response)["data"]]))"""


def copy_models(host):
    """The model ids one copy lists to the app's runtime key."""
    return json.loads(
        kubectl("exec", APP, "--", "python", "-c", COPY_MODELS, f"http://{host}:4000")
    )


def timed(call, *args):
    started = time.monotonic()
    answer = call(*args)
    return answer, round(time.monotonic() - started, 1)


def wait_until(check, timeout, message):
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() >= deadline:
            raise RuntimeError(message)
        time.sleep(0.5)


def run_cases():
    context = subprocess.check_output(
        ["kubectl", "--kubeconfig", KUBECONFIG, "config", "current-context"],
        text=True,
    ).strip()
    if context != "kind-keeplane":
        raise SystemExit(
            f"Refusing Kubernetes context {context!r}; expected kind-keeplane"
        )
    total = copy_count()
    replicas = json.loads(kubectl("get", "statefulset", COPIES, "-o", "json"))
    if total < 2 or replicas["status"].get("readyReplicas") != total:
        raise RuntimeError(f"Expected {total} ready gateway copies, at least two")
    # Not every copy confirms while one is stopped: one of them is missing.
    readback = SimpleNamespace(total=total, confirmed=total - 1, misconfigured=False)
    stopped = f"{COPIES}-{total - 1}"
    full = slow_stream_text()

    browser = Browser(BASE)
    if (
        browser.login(
            "first-admin", (RUNTIME / "first-admin-password").read_text().strip()
        )[0]
        != 200
    ):
        raise RuntimeError("Admin sign-in failed")

    def listing():
        status, body, _ = browser.fetch("/api/models")
        if status != 200:
            raise RuntimeError(f"Models listing answered {status}")
        return {model["id"]: model for model in body.get("models", [])}

    def add(name, classes):
        status, body, _ = browser.fetch(
            "/api/models",
            {
                "name": name,
                "source": "fixture",
                "model": "mock-local",
                "approved_classes": classes,
            },
        )
        return status, body

    def set_up(name, classes):
        status, body, _ = browser.fetch(
            f"/api/models/{name}/setup",
            {"key_choice": "none", "approved_classes": classes},
        )
        return status, body

    def remove(name):
        status, body, _ = browser.fetch(
            f"/api/models/{name}/setup", {}, method="DELETE"
        )
        return status, body

    results = []

    def check(case, okay, observed):
        results.append(
            {"case": case, "verdict": "pass" if okay else "fail", "observed": observed}
        )

    original_mode = None
    added_classes = []
    scaled_down = False
    process = None
    cleanup_errors = []
    try:
        # Data classes on, with two classes, so access can narrow and widen.
        status, data_classes, _ = browser.fetch("/api/data-classes")
        original_mode = data_classes["enabled"]
        if not original_mode:
            browser.fetch("/api/data-classes/mode", {"enabled": True}, method="PUT")
        names = [
            item["name"] for item in browser.fetch("/api/data-classes")[1]["classes"]
        ]
        for index in range(len(names), 2):
            status, created, _ = browser.fetch(
                "/api/data-classes",
                {"name": f"Copy stop {index} {SUFFIX}", "approved_model_ids": []},
            )
            if status != 201:
                raise RuntimeError("Could not add a data class for the check")
            added_classes.append(created["id"])
            names.append(created["name"])
        first, second = names[:2]

        # With every copy up, set up one model on two classes and one on one.
        for name, classes in ((WITHDRAW, [first, second]), (REMOVE, [first])):
            status, body = add(name, classes)
            if status != 200:
                raise RuntimeError(f"Could not add {name} with every copy up: {body}")

        # K8S-18: a reply streaming from the copy that stops.
        pod_ip = copy_pods()[stopped]["status"]["podIP"]
        process, events = start_probe(pod_ip, WITHDRAW)
        before, early_end = collect(
            events,
            lambda c, e: len(c) >= 2 or e is not None,
            time.monotonic() + 30,
        )
        kubectl("scale", "statefulset/" + COPIES, f"--replicas={total - 1}")
        scaled_down = True
        subprocess.run(
            [
                "kubectl",
                "--kubeconfig",
                KUBECONFIG,
                "-n",
                NAMESPACE,
                "delete",
                "pod",
                stopped,
                "--grace-period=0",
                "--force",
                "--wait=false",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        stopped_at = time.monotonic()
        after, end = collect(events, lambda c, e: e is not None, time.monotonic() + 60)
        end = end or early_end
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass
        stop_probe(process)
        process = None
        wait_until(
            lambda: stopped not in copy_pods(), 90, "The stopped copy's pod stayed"
        )
        wait_until(
            lambda: stopped not in ready_endpoints() and ready_endpoints(),
            30,
            "The gateway Service did not drop the stopped copy",
        )
        serving = ready_endpoints()
        retry = stream_once(SERVICE_HOST, WITHDRAW)
        received = (end or {}).get("content", "")
        interrupted_visibly = bool(
            end
            and (end["error"] or not end["done"])
            and received != full
            and full.startswith(received)
        )
        check(
            "K8S-18",
            len(before) >= 2
            and interrupted_visibly
            and retry is not None
            and retry["status"] == 200
            and retry["done"]
            and retry["finish"] == "stop"
            and retry["error"] is None
            and retry["content"] == full
            and serving == [f"{COPIES}-{n}" for n in range(total - 1)],
            {
                "stopped_copy": stopped,
                "pieces_before_stop": len(before),
                "pieces_after_stop": len(after),
                "seconds_to_end_after_stop": round(time.monotonic() - stopped_at, 1)
                if end
                else None,
                "interrupted": {
                    key: (end or {}).get(key)
                    for key in ("status", "done", "finish", "error")
                }
                | {"characters": len(received), "of": len(full)},
                "copies_serving_retry": serving,
                "retry": {
                    key: (retry or {}).get(key)
                    for key in ("status", "done", "finish", "error")
                }
                | {"complete_answer": (retry or {}).get("content") == full},
            },
        )

        # K8S-19: withdrawing access is saved while the copy is down, without
        # waiting on it (the copy readback gives up within about 5 seconds).
        (narrow_status, _), narrow_seconds = timed(set_up, WITHDRAW, [first])
        (remove_status, removed), remove_seconds = timed(remove, REMOVE)
        models = listing()
        expected_removal = removed_but_listed(REMOVE, readback)
        check(
            "K8S-19",
            narrow_status == 200
            and models.get(WITHDRAW, {}).get("approved") is True
            and models[WITHDRAW]["approved_classes"] == [first]
            and remove_status == 503
            and removed == expected_removal
            and not models.get(REMOVE, {}).get("approved")
            and narrow_seconds < 10
            and remove_seconds < 10,
            {
                "narrow_status": narrow_status,
                "narrow_seconds": narrow_seconds,
                "classes_after_narrowing": models.get(WITHDRAW, {}).get(
                    "approved_classes"
                ),
                "remove_status": remove_status,
                "remove_seconds": remove_seconds,
                "remove_message": removed,
                "removed_still_set_up": bool(models.get(REMOVE, {}).get("approved")),
            },
        )

        # K8S-20: adding or widening access is refused while the copy is down.
        add_status, add_body = add(ADD, [first])
        widen_status, widen_body = set_up(WITHDRAW, [first, second])
        models = listing()
        # Nothing was saved: the surviving first copy does not list the model
        # either (allowing it a moment to drop the undone registration).
        survivor = f"{COPIES}-0"
        survivor_ip = copy_pods()[survivor]["status"]["podIP"]
        survivor_lists_add = True
        deadline = time.monotonic() + 30
        while survivor_lists_add and time.monotonic() < deadline:
            survivor_lists_add = ADD in copy_models(survivor_ip)
            if survivor_lists_add:
                time.sleep(1)
        check(
            "K8S-20",
            add_status == 503
            and add_body == not_added(ADD, readback, True)
            and ADD not in models
            and not survivor_lists_add
            and widen_status == 503
            and widen_body == not_changed(WITHDRAW, readback)
            and models.get(WITHDRAW, {}).get("approved_classes") == [first],
            {
                "add_status": add_status,
                "add_message": add_body,
                "added_model_listed": ADD in models,
                "surviving_copy": survivor,
                "added_model_on_surviving_copy": survivor_lists_add,
                "widen_status": widen_status,
                "widen_message": widen_body,
                "classes_after_refused_widening": models.get(WITHDRAW, {}).get(
                    "approved_classes"
                ),
            },
        )

        # K8S-21: once the copy is back, the same add and widening succeed.
        kubectl("scale", "statefulset/" + COPIES, f"--replicas={total}")
        subprocess.run(
            [
                "kubectl",
                "--kubeconfig",
                KUBECONFIG,
                "-n",
                NAMESPACE,
                "rollout",
                "status",
                "statefulset/" + COPIES,
                "--timeout=180s",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        scaled_down = False
        ready = sorted(name for name, pod in copy_pods().items() if is_ready(pod))
        add_status, add_body = add(ADD, [first])
        widen_status, widen_body = set_up(WITHDRAW, [first, second])
        models = listing()
        check(
            "K8S-21",
            len(ready) == total
            and add_status == 200
            and models.get(ADD, {}).get("approved") is True
            and models[ADD]["approved_classes"] == [first]
            and widen_status == 200
            and sorted(models.get(WITHDRAW, {}).get("approved_classes", []))
            == sorted([first, second]),
            {
                "ready_copies": ready,
                "add_status": add_status,
                "add_error": (add_body or {}).get("error"),
                "added_classes": models.get(ADD, {}).get("approved_classes"),
                "widen_status": widen_status,
                "widen_error": (widen_body or {}).get("error"),
                "classes_after_widening": models.get(WITHDRAW, {}).get(
                    "approved_classes"
                ),
            },
        )
    finally:
        # Each step runs on its own, so a failing step neither skips the rest
        # nor replaces the error that ended the cases.
        def attempt(step, call, *args, **kwargs):
            try:
                call(*args, **kwargs)
            except Exception as error:
                cleanup_errors.append(f"{step}: {error!r}")
                print(f"Cleanup step failed: {step}: {error!r}", file=sys.stderr)

        attempt("stop the stream probe", stop_probe, process)
        if scaled_down:
            attempt(
                "scale the gateway copies back",
                kubectl,
                "scale",
                "statefulset/" + COPIES,
                f"--replicas={total}",
            )
            attempt(
                "wait for the gateway copies",
                subprocess.run,
                [
                    "kubectl",
                    "--kubeconfig",
                    KUBECONFIG,
                    "-n",
                    NAMESPACE,
                    "rollout",
                    "status",
                    "statefulset/" + COPIES,
                    "--timeout=180s",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
            )
        # Remove every check model, set up or not: a refused or half-done
        # change can leave one registered without an approval.
        for name in (WITHDRAW, REMOVE, ADD):
            attempt(f"remove {name}", remove, name)
        for identifier in added_classes:
            attempt(
                f"remove data class {identifier}",
                browser.fetch,
                f"/api/data-classes/{identifier}",
                {},
                method="DELETE",
            )
        if original_mode is False:
            attempt(
                "turn data classes back off",
                browser.fetch,
                "/api/data-classes/mode",
                {"enabled": False},
                method="PUT",
            )
    if cleanup_errors:
        raise RuntimeError("Cleanup failed: " + "; ".join(cleanup_errors))

    print(
        json.dumps(
            {"suite": "Keeplane gateway copy stop", "results": results}, indent=2
        )
    )
    return 1 if any(r["verdict"] == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(run_cases())


def test_gateway_copy_stop(monkeypatch, report_file, request, capsys):
    monkeypatch.setattr("sys.argv", [__file__])
    assert run_cases() in (None, 0)
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    verify_cases(__file__, output.out, globals().get("REPORT", report_file))


pytestmark = [pytest.mark.kubernetes]
