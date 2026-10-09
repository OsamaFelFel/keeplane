"""Check discovery against a served model without llama.cpp's /props API."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from threading import Thread


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components" / "control-plane"))
os.environ.pop("ACCOUNT_DB", None)
import server  # noqa: E402


class Runner(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/v1/models":
            self.send_error(404)
            return
        body = json.dumps({"data": [{"id": "plain-runner"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def main():
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Runner)
    thread = Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{fixture.server_port}"
    try:
        server.RUNNER_URLS.add(address)
        status, result = server.local_runner(address)
    finally:
        fixture.shutdown()
        fixture.server_close()
    passed = status == 200 and result == {"models": ["plain-runner"], "runtime": {}}
    print(json.dumps({"case": "LOCAL-25", "verdict": "pass" if passed else "fail",
                      "observed": {"status": status, "models": result.get("models"),
                                   "runtime": result.get("runtime")}}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
