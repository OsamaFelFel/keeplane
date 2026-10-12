"""Django's HTTPS CSRF rules and DRF exemption handling, without live stores."""

import json
import sys
import unittest

sys.path.insert(0, "/app")
from django.conf import settings
settings.configure(SECRET_KEY="isolated-csrf-test", ALLOWED_HOSTS=["127.0.0.1"],
                   CSRF_TRUSTED_ORIGINS=["https://keeplane.example.test"],
                   CSRF_COOKIE_SECURE=True, CSRF_COOKIE_HTTPONLY=True,
                   CSRF_COOKIE_SAMESITE="Strict", CSRF_FAILURE_VIEW="django_api.security.csrf_failure",
                   SECURE_PROXY_SSL_HEADER=("HTTP_X_KEEPLANE_SCHEME", "https"))
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.test import RequestFactory
from django.views.decorators.csrf import csrf_exempt
from django_api.security import BrowserCsrfMiddleware


class HttpsCsrfTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = BrowserCsrfMiddleware(lambda request: JsonResponse({}))
        request = self.factory.get("/api/auth-options")
        self.middleware.process_request(request)
        self.token = get_token(request)
        self.bootstrap = self.middleware.process_response(request, JsonResponse({}))
        self.cookie = self.bootstrap.cookies["csrftoken"].value

    def check(self, **headers):
        request = self.factory.post("/api/session", data="{}", content_type="application/json",
                                    HTTP_COOKIE="csrftoken=" + self.cookie,
                                    HTTP_X_KEEPLANE_SCHEME="https", **headers)
        self.middleware.process_request(request)
        denied = self.middleware.process_view(request, csrf_exempt(lambda request: None), (), {})
        return denied

    def test_https_01_secure_cookie(self):
        cookie = self.bootstrap.cookies["csrftoken"]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")

    def test_https_02_trusted_origin_requires_token(self):
        self.assertEqual(self.check(HTTP_ORIGIN="https://keeplane.example.test").status_code, 403)
        self.assertIsNone(self.check(HTTP_ORIGIN="https://keeplane.example.test", HTTP_X_CSRFTOKEN=self.token))

    def test_https_03_referer_is_required_without_origin(self):
        self.assertEqual(self.check(HTTP_X_CSRFTOKEN=self.token).status_code, 403)
        self.assertEqual(self.check(HTTP_X_CSRFTOKEN=self.token,
                                   HTTP_REFERER="http://keeplane.example.test/").status_code, 403)
        self.assertEqual(self.check(HTTP_X_CSRFTOKEN=self.token,
                                   HTTP_REFERER="https://foreign.example/").status_code, 403)
        self.assertIsNone(self.check(HTTP_X_CSRFTOKEN=self.token,
                                    HTTP_REFERER="https://keeplane.example.test/"))

    def test_https_04_drf_exemption_does_not_bypass_browser_checks(self):
        denied = self.check(HTTP_ORIGIN="https://foreign.example", HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(json.loads(denied.content), {"error": "Reload Keeplane and try again.", "code": "csrf_failed"})


if __name__ == "__main__":
    result = unittest.main(exit=False)
    print(json.dumps({"results": [{"case": "HTTPS-CSRF-0" + str(index), "verdict": "pass" if
                      result.result.wasSuccessful() else "fail"} for index in range(1, 5)]}))
    raise SystemExit(not result.result.wasSuccessful())
