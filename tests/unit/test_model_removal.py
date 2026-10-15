"""Model removal contract checks without a live gateway."""

import json
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components/control-plane"))

from gateway_adapter import AgentgatewayModelAdapter
from audit import AuditStore
from data_classes import DataClassStore
from model_catalog import ModelCatalog, fingerprint
from model_removal import remove_model_setup


MODEL = "model-one"
ACTOR = ("admin-id", "first-admin")
RESOURCE = {"id": MODEL, "revision": 1, "value": {
    "provider": {"custom": {"formats": [{"type": "completions"}]}},
    "params": {"model": "mock-local", "baseUrl": "http://model:18080/v1"},
}}


class Catalog:
    def __init__(self, owned=True, key_choice="none", revision=1):
        self.approval = {"gateway_fingerprint": fingerprint(MODEL, [dict(RESOURCE, revision=revision)]),
                         "key_choice": key_choice, "approved_classes": ["Public"],
                         "owned_by_keeplane": owned}
        self.removals = []

    def get(self, model_id):
        return self.approval if model_id == MODEL else None

    def remove(self, model_id, actor, gateway_removed=False):
        self.removals.append((model_id, actor, gateway_removed))
        self.approval = None
        return True


class Gateway:
    def __init__(self, resources=None, delete_status=200):
        self.registry = [RESOURCE] if resources is None else resources
        self.delete_status = delete_status
        self.read_count = 0
        self.deletions = []

    def resources(self):
        self.read_count += 1
        return 200, {"resources": self.registry}

    def delete_model(self, model_id):
        self.deletions.append(model_id)
        return self.delete_status, {} if self.delete_status == 200 else {"error": "Gateway rejected deletion"}


class ModelRemovalTests(unittest.TestCase):
    def test_mr_01_outside_setup_never_deletes_gateway_resource(self):
        catalog, gateway = Catalog(owned=False), Gateway()
        status, result = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual((status, result["gateway_model_preserved"]), (200, True))
        self.assertEqual(catalog.removals, [(MODEL, ACTOR, False)])
        self.assertEqual((gateway.read_count, gateway.deletions), (0, []))

    def test_mr_02_changed_owned_resource_is_preserved(self):
        catalog, gateway = Catalog(), Gateway(resources=[dict(RESOURCE, revision=2)])
        status, _ = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual(status, 409)
        self.assertEqual(gateway.deletions, [])
        self.assertEqual(catalog.removals, [])

    def test_mr_03_gateway_failure_retains_approval(self):
        catalog, gateway = Catalog(), Gateway(delete_status=503)
        status, result = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual((status, result["error"]), (503, "Gateway rejected deletion"))
        self.assertEqual(catalog.removals, [])

    def test_mr_04_owned_model_is_deleted_from_both_stores(self):
        catalog, gateway = Catalog(), Gateway()
        status, result = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual((status, result), (200, {"removed_from_keeplane": True,
                                                "gateway_model_preserved": False}))
        self.assertEqual(gateway.deletions, [MODEL])
        self.assertEqual(catalog.removals, [(MODEL, ACTOR, True)])

    def test_mr_05_shared_key_is_removed_after_gateway_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / ("key-" + "a" * 32)
            key.write_text("private-fixture-key")
            resource = json.loads(json.dumps(RESOURCE))
            resource["value"]["auth"] = {"key": {"value": {"file": str(key)}}}
            catalog = Catalog(key_choice="shared")
            catalog.approval["gateway_fingerprint"] = fingerprint(MODEL, [resource])
            status, _ = remove_model_setup(MODEL, ACTOR, catalog, Gateway([resource]), None, directory)
            self.assertEqual(status, 200)
            self.assertFalse(key.exists())

    def test_mr_06_adapter_delete_uses_management_key(self):
        seen = []
        class Reply(BytesIO):
            status = 200
        def respond(request, timeout):
            seen.append((request.get_method(), request.full_url, request.get_header("Authorization")))
            return Reply(b"{}")
        with tempfile.TemporaryDirectory() as directory:
            runtime, admin = Path(directory) / "runtime", Path(directory) / "admin"
            runtime.write_text("runtime-fixture")
            admin.write_text("admin-fixture")
            with patch("gateway_adapter.urlopen", respond):
                status, _ = AgentgatewayModelAdapter("http://gateway:4000", runtime, admin).delete_model(MODEL)
        self.assertEqual(status, 200)
        self.assertEqual(seen, [("DELETE", "http://gateway:4000/api/config/resources/llm.model/model-one",
                                 "Bearer admin-fixture")])

    def test_mr_07_removal_and_audit_commit_together(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "settings.sqlite3"
            audit = AuditStore(database)
            DataClassStore(database, audit)
            catalog = ModelCatalog(database, audit)
            audit.set_option("settings", True)
            catalog.approve(MODEL, [], fingerprint(MODEL, [RESOURCE]), ACTOR,
                            owned_by_keeplane=False)
            status, _ = remove_model_setup(MODEL, ACTOR, catalog, Gateway(), None, "")
            records = audit.records(kind="settings", search=MODEL)["records"]
            self.assertEqual(status, 200)
            self.assertIsNone(catalog.get(MODEL))
            self.assertTrue(any("Removed Keeplane setup" in item["what"] for item in records))


if __name__ == "__main__":
    unittest.main(verbosity=2)
