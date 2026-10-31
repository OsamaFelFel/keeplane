"""Model removal contract checks without a live gateway."""

import json
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "components/control-plane")
)

from common.errors import GatewayRemovalFailed, StorageUnavailable
from integrations.gateway.adapter import AgentgatewayModelAdapter
from model_registry.fingerprints import fingerprint
from model_registry.removal import remove_model_setup


MODEL = "model-one"
ACTOR = ("admin-id", "first-admin")
RESOURCE = {
    "id": MODEL,
    "revision": 1,
    "value": {
        "provider": {"custom": {"formats": [{"type": "completions"}]}},
        "params": {"model": "mock-local", "baseUrl": "http://model:18080/v1"},
    },
}


class Catalog:
    """Behaves like one settings transaction: nothing is kept unless it commits.

    fail is None, "write" (the approval or record write fails before the
    gateway step) or "commit" (the commit fails after the gateway step).
    """

    def __init__(self, owned=True, key_choice="none", revision=1, fail=None):
        self.fail = fail
        self.repinned = []
        self.approval = {
            "gateway_fingerprint": fingerprint(
                MODEL, [dict(RESOURCE, revision=revision)]
            ),
            "key_choice": key_choice,
            "approved_classes": ["Public"],
            "owned_by_keeplane": owned,
        }
        self.removals = []

    def get(self, model_id):
        return self.approval if model_id == MODEL else None

    def remove(self, model_id, actor, remove_from_gateway=None):
        if self.fail == "write":
            raise StorageUnavailable("Keeplane storage is unavailable")
        if remove_from_gateway:
            status, result = remove_from_gateway()
            if status != 200:
                raise GatewayRemovalFailed(status, result)
        if self.fail == "commit":
            raise StorageUnavailable("Keeplane storage is unavailable")
        self.removals.append((model_id, actor, bool(remove_from_gateway)))
        self.approval = None
        return True

    def approve(self, model_id, classes, revision, actor, **options):
        self.repinned.append((model_id, classes, revision, actor, options))
        self.approval = dict(self.approval, gateway_fingerprint=revision)


class Gateway:
    def __init__(self, resources=None, delete_status=200, restore_status=200):
        self.registry = [RESOURCE] if resources is None else resources
        self.delete_status = delete_status
        self.restore_status = restore_status
        self.read_count = 0
        self.deletions = []
        self.restores = []

    def resources(self):
        self.read_count += 1
        return 200, {"resources": self.registry}

    def delete_model(self, model_id):
        self.deletions.append(model_id)
        if self.delete_status != 200:
            return self.delete_status, {"error": "Gateway rejected deletion"}
        self.registry = [item for item in self.registry if item["id"] != model_id]
        return 200, {}

    def restore_model(self, value):
        self.restores.append(value)
        if self.restore_status != 200:
            return self.restore_status, {"error": "Gateway unavailable"}
        # A write back is a new gateway revision.
        self.registry = self.registry + [
            {"id": value.get("id", MODEL), "revision": 7, "value": json.loads(json.dumps(value))}
        ]
        return 200, {}


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
        self.assertIsNotNone(catalog.approval)
        self.assertEqual((gateway.registry, gateway.restores), ([RESOURCE], []))

    def test_mr_04_owned_model_is_deleted_from_both_stores(self):
        catalog, gateway = Catalog(), Gateway()
        status, result = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual(
            (status, result),
            (200, {"removed_from_keeplane": True, "gateway_model_preserved": False}),
        )
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
            status, _ = remove_model_setup(
                MODEL, ACTOR, catalog, Gateway([resource]), None, directory
            )
            self.assertEqual(status, 200)
            self.assertFalse(key.exists())

    def test_mr_06_adapter_delete_uses_management_key(self):
        seen = []

        class Reply(BytesIO):
            status = 200

        def respond(request, timeout):
            seen.append(
                (
                    request.get_method(),
                    request.full_url,
                    request.get_header("Authorization"),
                )
            )
            return Reply(b"{}")

        with tempfile.TemporaryDirectory() as directory:
            runtime, admin = Path(directory) / "runtime", Path(directory) / "admin"
            runtime.write_text("runtime-fixture")
            admin.write_text("admin-fixture")
            with patch("integrations.gateway.adapter.urlopen", respond):
                status, _ = AgentgatewayModelAdapter(
                    "http://gateway:4000", runtime, admin
                ).delete_model(MODEL)
        self.assertEqual(status, 200)
        self.assertEqual(
            seen,
            [
                (
                    "DELETE",
                    "http://gateway:4000/api/config/resources/llm.model/model-one",
                    "Bearer admin-fixture",
                )
            ],
        )

    def test_mr_08_failed_write_never_deletes_from_gateway(self):
        catalog, gateway = Catalog(fail="write"), Gateway()
        with self.assertRaises(StorageUnavailable):
            remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual((gateway.deletions, gateway.registry), ([], [RESOURCE]))
        self.assertIsNotNone(catalog.approval)

    def test_mr_09_failed_commit_restores_and_repins_the_model(self):
        catalog, gateway = Catalog(fail="commit"), Gateway()
        status, result = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual(status, 503)
        self.assertEqual(
            result["error"],
            "Keeplane couldn't record the removal. "
            "The model is back in the gateway and nothing changed.",
        )
        self.assertEqual(gateway.restores, [RESOURCE["value"]])
        self.assertEqual([item["value"] for item in gateway.registry], [RESOURCE["value"]])
        self.assertEqual(catalog.removals, [])
        restored = fingerprint(MODEL, gateway.registry)
        self.assertEqual(catalog.approval["gateway_fingerprint"], restored)
        self.assertEqual(
            catalog.repinned,
            [
                (
                    MODEL,
                    ["Public"],
                    restored,
                    None,
                    {"owned_by_keeplane": True, "key_choice": "none"},
                )
            ],
        )

    def test_mr_10_failed_restore_is_reported(self):
        catalog = Catalog(fail="commit")
        gateway = Gateway(restore_status=503)
        status, result = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual(status, 503)
        self.assertEqual(
            result["error"],
            "Keeplane couldn't record the removal. "
            "The model may be missing from the gateway; check Models.",
        )
        self.assertEqual(catalog.repinned, [])

    def test_mr_11_shared_key_is_kept_when_removal_is_not_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / ("key-" + "a" * 32)
            key.write_text("private-fixture-key")
            resource = json.loads(json.dumps(RESOURCE))
            resource["value"]["auth"] = {"key": {"value": {"file": str(key)}}}
            catalog = Catalog(key_choice="shared", fail="commit")
            catalog.approval["gateway_fingerprint"] = fingerprint(MODEL, [resource])
            gateway = Gateway([resource])
            status, _ = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, directory)
            self.assertEqual(status, 503)
            self.assertTrue(key.exists())
            self.assertEqual(gateway.restores, [resource["value"]])

    def test_mr_12_outside_model_is_never_deleted_or_restored(self):
        catalog, gateway = Catalog(owned=False, fail="write"), Gateway()
        with self.assertRaises(StorageUnavailable):
            remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual((gateway.deletions, gateway.restores), ([], []))

    def test_mr_13_adapter_restore_writes_the_previous_definition(self):
        seen = []

        class Reply(BytesIO):
            status = 200

        def respond(request, timeout):
            seen.append((request.get_method(), request.full_url, json.loads(request.data)))
            return Reply(b"{}")

        with tempfile.TemporaryDirectory() as directory:
            admin = Path(directory) / "admin"
            admin.write_text("admin-fixture")
            with patch("integrations.gateway.adapter.urlopen", respond):
                status, _ = AgentgatewayModelAdapter(
                    "http://gateway:4000", None, admin
                ).restore_model(RESOURCE["value"])
        self.assertEqual(status, 200)
        self.assertEqual(
            seen,
            [
                (
                    "PUT",
                    "http://gateway:4000/api/config/resources/llm.model",
                    {"resources": [{"value": RESOURCE["value"]}]},
                )
            ],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
