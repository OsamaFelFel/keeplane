"""Stream one chat answer from a gateway address and say how it ended.

The live Kubernetes check runs this file inside the app pod (it reads the
app's gateway runtime key there), so it uses only Python's standard library.
It prints one JSON line per content piece as it arrives, then one final line:

    {"event": "end", "status": ..., "content": ..., "done": ...,
     "finish": ..., "error": ...}

`done` is true only when the gateway sent `data: [DONE]`; `finish` is the
last finish_reason it sent; `error` names a transport failure, a non-200
status or an error event. A reply cut short shows as an error or a missing
`[DONE]`, never as a complete answer.

Usage: python stream_probe.py HOST PORT MODEL PROMPT [KEY_FILE]
"""

import http.client
import json
import sys

KEY_FILE = "/run/gateway-keys/runtime-key"
READ_TIMEOUT = 10


def emit(**event):
    print(json.dumps(event), flush=True)


def lines(response):
    """Yield the body's lines as they arrive.

    read1 raises IncompleteRead when a chunked body stops before its last
    chunk; HTTPResponse.readline would end quietly instead.
    """
    buffer = b""
    while True:
        data = response.read1(65536)
        if not data:
            break
        buffer += data
        *complete, buffer = buffer.split(b"\n")
        yield from complete
    if buffer:
        yield buffer


def stream(host, port, model, prompt, key):
    status, content, done, finish, error = None, "", False, None, None
    body = json.dumps(
        {
            "model": model,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        }
    )
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    try:
        connection = http.client.HTTPConnection(host, port, timeout=READ_TIMEOUT)
        connection.request("POST", "/v1/chat/completions", body, headers)
        response = connection.getresponse()
        status = response.status
        if status != 200:
            error = f"HTTP {status}"
        else:
            for line in lines(response):
                line = line.decode().strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    done = True
                    continue
                chunk = json.loads(data)
                if chunk.get("error"):
                    error = "error event: " + json.dumps(chunk["error"])[:200]
                    continue
                for choice in chunk.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content") or ""
                    content += piece
                    finish = choice.get("finish_reason") or finish
                    if piece:
                        emit(event="chunk", content=piece)
        connection.close()
    except Exception as failure:  # noqa: BLE001 - every failure is reported
        error = f"{type(failure).__name__}: {failure}"[:300]
    return {
        "event": "end",
        "status": status,
        "content": content,
        "done": done,
        "finish": finish,
        "error": error,
    }


def main(argv):
    host, port, model, prompt = argv[1], int(argv[2]), argv[3], argv[4]
    key_file = argv[5] if len(argv) > 5 else KEY_FILE
    key = ""
    if key_file != "-":
        with open(key_file) as handle:
            key = handle.read().strip()
    emit(**stream(host, port, model, prompt, key))


if __name__ == "__main__":
    main(sys.argv)
