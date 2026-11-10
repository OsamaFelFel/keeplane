"""A stand-in coding runtime for the sign-in restart and outage cases.

It answers `--version` as OpenCode V2 2.0.27 and, for `run`, sends the turn's
model calls the way the runtime does: to the provider address and with the
grant and headers that `keeplane code` gives it, so they pass through the
CLI's usage relay to the gateway. It prints one JSON event per call, as the
runtime does, and an error event with the HTTP status when a call fails.

The real runtime's own retries and tools are covered by the developer
journey; this stand-in exists so a case can stop the turn between two calls
and restart the app or PostgreSQL, or stop the gateway, at that moment.
`plan.json` in the control folder (the first argument) sets the number of
calls and after which one to pause: the stand-in writes `paused` and waits
for `resume`.
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


def event(value):
    print(json.dumps(value), flush=True)


def call(base, model, grant, headers, step):
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": f"step {step}"}]}
    ).encode()
    sent = Request(
        base.rstrip("/") + "/chat/completions",
        body,
        {
            "Authorization": "Bearer " + grant,
            "Content-Type": "application/json",
            **headers,
        },
    )
    try:
        with build_opener(ProxyHandler({})).open(sent, timeout=60) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        try:
            raw = error.read(4096)
        finally:
            error.close()
        try:
            message = json.loads(raw)
        except ValueError:
            message = raw.decode("utf-8", "replace")
        return error.code, message
    except (URLError, OSError) as error:
        return None, type(error).__name__


def run(control):
    plan = json.loads((control / "plan.json").read_text())
    config = json.loads(os.environ["OPENCODE_CONFIG_CONTENT"])
    provider = config["providers"]["keeplane"]
    model = config["model"].removeprefix("keeplane/")
    grant = os.environ["KEEPLANE_RUNTIME_GRANT"]
    sys.stdin.read()
    for step in range(1, plan["calls"] + 1):
        if plan.get("pause_after") == step - 1 and step > 1:
            (control / "paused").touch()
            deadline = time.monotonic() + 180
            while not (control / "resume").exists():
                if time.monotonic() > deadline:
                    return 3
                time.sleep(0.1)
        status, answer = call(
            provider["settings"]["baseURL"],
            model,
            grant,
            provider.get("headers", {}),
            step,
        )
        with (control / "calls").open("a") as calls:
            calls.write(json.dumps({"step": step, "status": status}) + "\n")
        if status != 200:
            event(
                {
                    "type": "error",
                    "error": {
                        "name": "APIError",
                        "data": {
                            "message": json.dumps(answer)[:500],
                            "statusCode": status,
                            "isRetryable": status is not None and status >= 500,
                        },
                    },
                }
            )
            return 1
        event(
            {
                "type": "text",
                "part": {
                    "text": answer["choices"][0]["message"]["content"],
                    "modelID": model,
                },
            }
        )
    return 0


if __name__ == "__main__":
    control = Path(sys.argv[1])
    if sys.argv[2:] == ["--version"]:
        print("2.0.27")
        raise SystemExit(0)
    raise SystemExit(run(control))
