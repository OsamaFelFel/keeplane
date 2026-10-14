"""Exercise the launcher's real HTTP sign-in against a CSRF-protected fixture."""

import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("local_up", Path(__file__).resolve().parents[2] / "deploy/local/up.py")
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)


class StartupCheck(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.refuse = False
        self.anonymous = False
        self.health_calls = 0
        case = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body, cookie=None):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if cookie:
                    self.send_header("Set-Cookie", cookie + "; Path=/")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def do_GET(self):
                if self.path == "/api/identity":
                    self.reply(200 if case.anonymous else 401, {})
                elif self.path == "/api/auth-options":
                    rotated = "session=live" in self.headers.get("Cookie", "")
                    token = "rotated" if rotated else "initial"
                    self.reply(200, {"csrf_token": token}, "csrftoken=" + token)
                elif self.path == "/health":
                    if "session=live" not in self.headers.get("Cookie", ""):
                        self.reply(401, {})
                        return
                    case.health_calls += 1
                    self.reply(503 if case.health_calls == 1 else 200,
                               {"gateway": "ready"})

            def do_POST(self):
                token = self.headers.get("X-CSRFToken")
                valid = (token and "csrftoken=" + token in self.headers.get("Cookie", "")
                         and self.headers.get("Origin") == case.base)
                if not valid or case.refuse:
                    self.reply(403, {"code": "csrf_failed"})
                    return
                if self.path == "/api/session":
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    case.assertEqual(body["password"], "fixture-password")
                    case.events.append("sign-in")
                    self.reply(200, {}, "session=live")
                elif self.path == "/sign-out":
                    case.assertEqual(token, "rotated")
                    case.events.append("sign-out")
                    self.reply(200, {}, "session=; Max-Age=0")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temp.name)
        (self.runtime / "first-admin-password").write_text("fixture-password")
        self.runtime_patch = patch.object(up, "RUNTIME", self.runtime)
        self.runtime_patch.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.runtime_patch.stop()
        self.temp.cleanup()

    def test_custom_port_csrf_rotation_one_login_and_cleanup_after_gateway_retry(self):
        with patch.object(up.time, "sleep"):
            up.wait_preview(self.base, timeout=5)
        self.assertEqual(self.events, ["sign-in", "sign-out"])
        self.assertEqual(self.health_calls, 2)

    def test_refused_sign_in_is_reported_without_waiting_for_timeout(self):
        self.refuse = True
        with patch.object(up.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                up.wait_preview(self.base)
        sleep.assert_not_called()

    def test_anonymous_admin_access_stops_startup(self):
        self.anonymous = True
        with self.assertRaisesRegex(RuntimeError, "anonymous access"):
            up.wait_preview(self.base)
        self.assertEqual(self.events, [])

    def test_gateway_timeout_still_revokes_the_check_session(self):
        with patch.object(up.time, "monotonic", side_effect=[0, 0, 10]), patch.object(up.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                up.wait_preview(self.base, timeout=1)
        self.assertEqual(self.events, ["sign-in", "sign-out"])


if __name__ == "__main__":
    unittest.main()
