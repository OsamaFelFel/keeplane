"""Contract checks for the small model-listing use case and gateway read adapter."""

import json
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components/control-plane"))

from gateway_adapter import AgentgatewayModelAdapter
from model_catalog import fingerprint
from model_listing import list_models


RESOURCE = {"id": "cloud-model", "revision": 1, "value": {
    "provider": "openAI", "params": {"model": "cloud-upstream"},
    "auth": {"key": {"value": "private-provider-secret"}},
}}


class Catalog:
    def __init__(self, approval):
        self.approval = approval

    def get(self, model_id):
        return self.approval if model_id == "cloud-model" else None


def listed(resources, catalog):
    return list_models(
        lambda: (200, {"data": [{"id": "cloud-model"}, {"id": "outside-model"}]}),
        lambda: (200, {"resources": resources}), catalog, None, set())


class ModelListingTests(unittest.TestCase):
    def test_ml_01_approved_and_outside_without_secrets(self):
        approval = {"gateway_fingerprint": fingerprint("cloud-model", [RESOURCE]),
                    "key_choice": "shared", "approved_classes": ["Public"],
                    "owned_by_keeplane": True}
        status, result = listed([RESOURCE], Catalog(approval))
        self.assertEqual(status, 200)
        managed, outside = result["models"]
        self.assertEqual((managed["provider"], managed["approved"], managed["key_choice"],
                          managed["approved_classes"]), ("OpenAI", True, "shared", ["Public"]))
        self.assertEqual((outside["approved"], outside["kind"]), (False, "unknown"))
        self.assertNotIn("private-provider-secret", json.dumps(result))

    def test_ml_02_changed_revision_revokes_approval(self):
        approval = {"gateway_fingerprint": fingerprint("cloud-model", [RESOURCE]),
                    "key_choice": "shared", "approved_classes": ["Public"],
                    "owned_by_keeplane": True}
        changed = dict(RESOURCE, revision=2)
        _, result = listed([changed], Catalog(approval))
        self.assertEqual(result["models"][0]["approved"], False)
        self.assertIsNone(result["models"][0]["key_choice"])

    def test_ml_03_gateway_failures_do_not_return_partial_lists(self):
        for failed in ("models", "resources"):
            reads = []
            def get_models():
                reads.append("models")
                return (503, {"error": "Gateway unavailable"}) if failed == "models" else (200, {"data": []})
            def get_resources():
                reads.append("resources")
                return 503, {"error": "Gateway unavailable"}
            status, result = list_models(get_models, get_resources, Catalog(None), None, set())
            self.assertEqual((status, result), (503, {"error": "Gateway unavailable"}))
            self.assertEqual(reads, ["models"] if failed == "models" else ["models", "resources"])

    def test_ml_04_runtime_and_admin_keys_are_separate(self):
        seen = []
        class Reply(BytesIO):
            status = 200

        def read(request, timeout):
            path = request.full_url.split("127.0.0.1", 1)[-1]
            seen.append((path, request.get_header("Authorization")))
            if path.startswith("/api/") and len([p for p, _ in seen if p.startswith("/api/")]) == 1:
                raise HTTPError(request.full_url, 500, "temporary", {}, BytesIO(b'{"error":"temporary"}'))
            data = {"data": []} if path == "/v1/models" else {"resources": []}
            return Reply(json.dumps(data).encode())

        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime"
            admin = Path(directory) / "admin"
            runtime.write_text("runtime-fixture")
            admin.write_text("admin-fixture")
            with patch("gateway_adapter.urlopen", read):
                reader = AgentgatewayModelAdapter("http://127.0.0.1", runtime, admin)
                self.assertEqual(reader.models()[0], 200)
                self.assertEqual(reader.resources()[0], 200)
        self.assertEqual(seen, [
            ("/v1/models", "Bearer runtime-fixture"),
            ("/api/config/resources/llm.model", "Bearer admin-fixture"),
            ("/api/config/resources/llm.model", "Bearer admin-fixture"),
        ])

    def test_ml_05_allowed_runner_classification(self):
        resource = {"id": "local-model", "revision": 1, "value": {
            "provider": "openAICompatible", "params": {"baseUrl": "http://custom-runner:8080/v1", "model": "served"},
        }}
        status, result = list_models(lambda: (200, {"data": [{"id": "local-model"}]}),
                                     lambda: (200, {"resources": [resource]}),
                                     Catalog(None), None, {"http://custom-runner:8080"})
        self.assertEqual(status, 200)
        self.assertEqual((result["models"][0]["provider"], result["models"][0]["kind"]),
                         ("Local runner", "real-local"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
