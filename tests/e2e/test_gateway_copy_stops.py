"""Stop one managed gateway copy in kind: mid-stream, and during admin changes.

Spec 002 ST4 "One gateway copy stops": a reply already streaming from the
stopped copy may fail visibly and can be retried (K8S-18, K8S-19). The model
change rule decided with keeplane #179: while a copy is down, an admin's add or
widening is refused and nothing is saved, and a withdrawal is saved at once
(K8S-20 to K8S-23).

It deletes one gateway pod and scales the gateway copies down and back up, so
it refuses any kubeconfig without the exact kind-keeplane context.
"""

import pytest

import json
import os
import queue
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from tests.support.client import RUNTIME, Browser
from tests.support.kind_trial import kind_kubeconfig


KUBECONFIG = kind_kubeconfig()
BASE = os.environ.get("KEEPLANE_BASE_URL", "http://127.0.0.1:13000")
NAMESPACE = "keeplane"
COPIES = "statefulset/keeplane-gateway"
# The model every managed gateway copy serves from its own configuration file
# (deploy/local/values.yaml); its upstream is the fixture in
# tests/fixtures/mock_model.py.
STREAM_MODEL = "local-fixture"
# tests/fixtures/mock_model.py: this prompt gets 40 word chunks, one every
# 0.25 seconds, then the final chunk and [DONE].
SLOW_PROMPT = "keeplane slow stream"
SLOW_TEXT = " ".join(f"word{n}" for n in range(1, 41))
CHECK_MODEL = "copy-check"
ADD_MODEL = "copy-down-add"
# The decided wording (keeplane #179, model_registry/copy_messages.py).
NOT_ADDED = (
    "Not every gateway copy confirmed it: {n} of {m} did. Nothing was saved. "
    "Check the gateway and try again."
)
NOT_CHANGED = (
    "Not every gateway copy confirmed the change: {n} of {m} did. Nothing was "
    "saved, and its earlier setup stays. Check the gateway and try again."
)
# The copy readback ends within about 5 seconds; a withdrawal does not wait
# for it.
READBACK_SECONDS = 5.0

# Runs inside the app pod, which holds the gateway runtime key. It prints one
# JSON line per event so the test can stop a copy while the reply streams.
STREAM = r"""import json,pathlib,sys,time,urllib.error,urllib.request
url,model,prompt=sys.argv[1:4]
key=pathlib.Path("/run/gateway-keys/runtime-key").read_text().strip()
body=json.dumps({"model":model,"stream":True,"messages":[{"role":"user","content":prompt}]}).encode()
request=urllib.request.Request(url+"/v1/chat/completions",data=body,headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
start=time.monotonic();chunks=0;done=False;finish=None;text="";error=None;status=None
def say(**fields):
 print(json.dumps(fields),flush=True)
try:
 with urllib.request.urlopen(request,timeout=20) as response:
  status=response.status
  say(event="open",status=status)
  for raw in response:
   line=raw.decode().strip()
   if not line.startswith("data:"):
    continue
   data=line[5:].strip()
   if data=="[DONE]":
    done=True
    continue
   for choice in json.loads(data).get("choices",[]):
    text+=choice.get("delta",{}).get("content") or ""
    finish=choice.get("finish_reason") or finish
   chunks+=1
   say(event="chunk",n=chunks)
except urllib.error.HTTPError as failure:
 status=failure.code
 error="HTTP %d"%failure.code
except Exception as failure:
 error=type(failure).__name__+": "+str(failure)[:200]
say(event="end",status=status,chunks=chunks,done=done,finish=finish,text=text,error=error,seconds=round(time.monotonic()-start,2))
"""


def kubectl(*args, timeout=180):
    return subprocess.check_output(
        ["kubectl", "--kubeconfig", KUBECONFIG, *args], text=True, timeout=timeout
    ).strip()


def ns(*args, **options):
    return kubectl("-n", NAMESPACE, *args, **options)


def app_env():
    deployment = json.loads(ns("get", "deployment", "keeplane-app", "-o", "json"))
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    return {item["name"]: item.get("value", "") for item in container["env"]}


class Stream:
    """A streamed model call made from the app pod, read line by line."""

    def __init__(self, url):
        self.events = queue.Queue()
        self.process = subprocess.Popen(
            [
                "kubectl", "--kubeconfig", KUBECONFIG, "-n", NAMESPACE, "exec",
                "deploy/keeplane-app", "--", "python", "-u", "-c", STREAM,
                url, STREAM_MODEL, SLOW_PROMPT,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            try:
                self.events.put(json.loads(line))
            except ValueError:
                continue
        self.events.put(None)

    def next(self, deadline):
        try:
            return self.events.get(timeout=max(0.1, deadline - time.monotonic()))
        except queue.Empty:
            return None

    def until(self, wanted, seconds):
        """Read until an event matches; returns it, or the end event, or None."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            event = self.next(deadline)
            if event is None or wanted(event) or event.get("event") == "end":
                return event
        return None

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=30)


def stream_once(url, seconds=60):
    stream = Stream(url)
    try:
        return stream.until(lambda event: event.get("event") == "end", seconds)
    finally:
        stream.close()


def complete(end):
    return bool(
        end
        and end.get("event") == "end"
        and end.get("status") == 200
        and end.get("done") is True
        and end.get("finish") == "stop"
        and end.get("text") == SLOW_TEXT
        and end.get("error") is None
    )


def ready_endpoints():
    slices = json.loads(
        ns(
            "get", "endpointslice", "-l",
            "kubernetes.io/service-name=keeplane", "-o", "json",
        )
    )["items"]
    return [
        {
            "pod": endpoint.get("targetRef", {}).get("name"),
            "uid": endpoint.get("targetRef", {}).get("uid"),
        }
        for item in slices
        for endpoint in item.get("endpoints", [])
        if endpoint.get("conditions", {}).get("ready") is True
    ]


def wait_for(condition, seconds, what):
    deadline = time.monotonic() + seconds
    while True:
        value = condition()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise RuntimeError(what)
        time.sleep(0.2)


def copies_ready(count):
    ns("rollout", "status", COPIES, "--timeout=180s", timeout=200)
    wait_for(
        lambda: json.loads(ns("get", COPIES, "-o", "json"))["status"].get(
            "readyReplicas"
        )
        == count
        and len(ready_endpoints()) == count,
        120,
        f"The gateway did not return to {count} ready copies",
    )


def model_row(browser, model_id):
    status, listing, _ = browser.fetch("/api/models")
    if status != 200:
        raise RuntimeError(f"The model list answered HTTP {status}")
    return next(
        (item for item in listing.get("models", []) if item["id"] == model_id), None
    )


def summary(row):
    if row is None:
        return None
    return {
        "approved": row.get("approved"),
        "approved_classes": row.get("approved_classes"),
    }


def timed(call):
    start = time.monotonic()
    status, body, _ = call()
    return status, body, round(time.monotonic() - start, 2)


def run_cases():
    context = kubectl("config", "current-context")
    if context != "kind-keeplane":
        raise SystemExit(
            f"Refusing Kubernetes context {context!r}; expected kind-keeplane"
        )
    results = []

    def check(case, okay, observed):
        results.append(
            {"case": case, "verdict": "pass" if okay else "fail", "observed": observed}
        )

    env = app_env()
    copy_urls = [url for url in env["GATEWAY_COPY_URLS"].split(",") if url]
    gateway_url = env["GATEWAY_URL"].rstrip("/")
    by_pod = {urlsplit(url).hostname.split(".")[0]: url for url in copy_urls}
    if sorted(by_pod) != ["keeplane-gateway-0", "keeplane-gateway-1"]:
        raise RuntimeError(f"Unexpected gateway copy list: {copy_urls}")
    copies_ready(2)

    # K8S-18 and K8S-19: stop the copy a reply is streaming from.
    stopped, survivor = "keeplane-gateway-0", "keeplane-gateway-1"
    stopped_uid = json.loads(ns("get", "pod", stopped, "-o", "json"))["metadata"][
        "uid"
    ]
    stream = Stream(by_pod[stopped])
    try:
        second = stream.until(
            lambda event: event.get("event") == "chunk" and event.get("n") >= 2, 60
        )
        received = second.get("n", 0) if second else 0
        streaming = bool(second and second.get("event") == "chunk")
        if streaming:
            # A short grace period: the copy stops while the reply still has
            # about nine seconds to go.
            ns("delete", "pod", stopped, "--grace-period=1", "--wait=false")
            stopped_at = time.monotonic()
            end = stream.until(lambda event: event.get("event") == "end", 60)
            ended_after = round(time.monotonic() - stopped_at, 2)
        else:
            end, ended_after = second, None
    finally:
        stream.close()
    check(
        "K8S-18",
        streaming
        and bool(end)
        and end.get("event") == "end"
        and end.get("status") == 200
        and end.get("done") is False
        and end.get("finish") is None
        and end.get("chunks", 0) >= received
        and end.get("text") != SLOW_TEXT,
        {
            "stopped_copy": stopped,
            "chunks_before_stop": received,
            "stream_end": end,
            "seconds_from_stop_to_end": ended_after,
        },
    )

    # Retry once the gateway Service no longer offers the stopped pod.
    wait_for(
        lambda: not any(item["uid"] == stopped_uid for item in ready_endpoints())
        and any(item["pod"] == survivor for item in ready_endpoints()),
        60,
        "The gateway Service did not drop the stopped copy",
    )
    offered = ready_endpoints()
    direct = stream_once(by_pod[survivor])
    through_service = stream_once(gateway_url)
    check(
        "K8S-19",
        complete(direct) and complete(through_service),
        {
            "survivor": survivor,
            "ready_endpoints_at_retry": [item["pod"] for item in offered],
            "retry_to_survivor": {
                key: direct.get(key) for key in ("status", "chunks", "done", "finish", "error")
            }
            if direct
            else None,
            "retry_through_gateway_service": {
                key: through_service.get(key)
                for key in ("status", "chunks", "done", "finish", "error")
            }
            if through_service
            else None,
        },
    )
    copies_ready(2)

    # K8S-20 to K8S-23: admin changes while one copy is down.
    browser = Browser(BASE)
    if browser.login(
        "first-admin", (RUNTIME / "first-admin-password").read_text().strip()
    )[0] != 200:
        raise RuntimeError("Admin sign-in failed")
    status, classes, _ = browser.fetch("/api/data-classes")
    turned_on = False
    scaled_down = False
    try:
        if status == 200 and not classes.get("enabled"):
            browser.fetch("/api/data-classes/mode", {"enabled": True}, method="PUT")
            turned_on = True
            status, classes, _ = browser.fetch("/api/data-classes")
        names = [item["name"] for item in classes.get("classes", [])]
        if status != 200 or len(names) < 2:
            raise RuntimeError("Two data classes are needed to widen access")
        narrow, wide = names[:1], names[:2]
        for model_id in (ADD_MODEL, CHECK_MODEL):
            if model_row(browser, model_id):
                browser.fetch(f"/api/models/{model_id}/setup", {}, method="DELETE")
        status, body, _ = browser.fetch(
            "/api/models",
            {
                "name": CHECK_MODEL,
                "source": "fixture",
                "model": "mock-local",
                "approved_classes": narrow,
            },
        )
        if status != 200:
            raise RuntimeError(f"Could not add {CHECK_MODEL}: {status} {body}")

        ns("scale", COPIES, "--replicas=1")
        scaled_down = True
        ns("wait", "--for=delete", "pod/keeplane-gateway-1", "--timeout=120s", timeout=140)
        wait_for(
            lambda: [item["pod"] for item in ready_endpoints()] == ["keeplane-gateway-0"],
            60,
            "The gateway Service still offers the scaled-down copy",
        )
        listed_copies = len(app_env()["GATEWAY_COPY_URLS"].split(","))

        add_status, add_body, add_seconds = timed(
            lambda: browser.fetch(
                "/api/models",
                {
                    "name": ADD_MODEL,
                    "source": "fixture",
                    "model": "mock-local",
                    "approved_classes": narrow,
                },
            )
        )
        after_add = model_row(browser, ADD_MODEL)
        check(
            "K8S-20",
            listed_copies == 2
            and add_status == 503
            and add_body
            == {
                "title": f"{ADD_MODEL} wasn't added",
                "error": NOT_ADDED.format(n=1, m=2),
            }
            and after_add is None,
            {
                "running_copies": 1,
                "listed_copies": listed_copies,
                "status": add_status,
                "reply": add_body,
                "seconds": add_seconds,
                "listed_after": summary(after_add),
            },
        )

        widen_status, widen_body, widen_seconds = timed(
            lambda: browser.fetch(
                f"/api/models/{CHECK_MODEL}/setup",
                {"key_choice": "none", "approved_classes": wide},
            )
        )
        after_widen = model_row(browser, CHECK_MODEL)
        check(
            "K8S-21",
            widen_status == 503
            and widen_body
            == {
                "title": f"{CHECK_MODEL} wasn't changed",
                "error": NOT_CHANGED.format(n=1, m=2),
            }
            and summary(after_widen)
            == {"approved": True, "approved_classes": narrow},
            {
                "asked_classes": wide,
                "status": widen_status,
                "reply": widen_body,
                "seconds": widen_seconds,
                "saved_after": summary(after_widen),
            },
        )

        withdraw_status, withdraw_body, withdraw_seconds = timed(
            lambda: browser.fetch(
                f"/api/models/{CHECK_MODEL}/setup",
                {"key_choice": "none", "approved_classes": []},
            )
        )
        after_withdraw = model_row(browser, CHECK_MODEL)
        check(
            "K8S-22",
            withdraw_status == 200
            and withdraw_seconds < READBACK_SECONDS
            and summary(after_withdraw) == {"approved": True, "approved_classes": []},
            {
                "asked_classes": [],
                "status": withdraw_status,
                "reply": withdraw_body,
                "seconds": withdraw_seconds,
                "saved_after": summary(after_withdraw),
            },
        )

        ns("scale", COPIES, "--replicas=2")
        copies_ready(2)
        scaled_down = False
        readd_status, readd_body, readd_seconds = timed(
            lambda: browser.fetch(
                "/api/models",
                {
                    "name": ADD_MODEL,
                    "source": "fixture",
                    "model": "mock-local",
                    "approved_classes": narrow,
                },
            )
        )
        rewiden_status, _, rewiden_seconds = timed(
            lambda: browser.fetch(
                f"/api/models/{CHECK_MODEL}/setup",
                {"key_choice": "none", "approved_classes": wide},
            )
        )
        after_return = {
            ADD_MODEL: summary(model_row(browser, ADD_MODEL)),
            CHECK_MODEL: summary(model_row(browser, CHECK_MODEL)),
        }
        check(
            "K8S-23",
            readd_status == 200
            and rewiden_status == 200
            and after_return
            == {
                ADD_MODEL: {"approved": True, "approved_classes": narrow},
                CHECK_MODEL: {"approved": True, "approved_classes": wide},
            },
            {
                "add_status": readd_status,
                "add_reply": readd_body,
                "add_seconds": readd_seconds,
                "widen_status": rewiden_status,
                "widen_seconds": rewiden_seconds,
                "saved_after": after_return,
            },
        )
    finally:
        if scaled_down:
            ns("scale", COPIES, "--replicas=2")
            copies_ready(2)
        for model_id in (ADD_MODEL, CHECK_MODEL):
            if model_row(browser, model_id):
                browser.fetch(f"/api/models/{model_id}/setup", {}, method="DELETE")
        if turned_on:
            browser.fetch("/api/data-classes/mode", {"enabled": False}, method="PUT")

    print(
        json.dumps(
            {"suite": "Keeplane gateway copy stops", "results": results}, indent=2
        )
    )
    return 1 if any(r["verdict"] == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(run_cases())


def test_gateway_copy_stops(monkeypatch, report_file, request, capsys):
    arguments = [__file__]
    monkeypatch.setattr("sys.argv", arguments)
    assert run_cases() in (None, 0)
    from tests.support.cases import verify_cases

    output = capsys.readouterr()
    print(output.out, end="")
    verify_cases(__file__, output.out, globals().get("REPORT", report_file))


pytestmark = [pytest.mark.kubernetes]
