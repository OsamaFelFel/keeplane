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
from model_registry.levels import ModelInUse
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
    gateway step), "commit" (the commit fails after the gateway step),
    "landed" (the commit reports a failure but was kept), "changed" (another
    request changes the setup after the failed commit) or "gone" (another
    request removed the approval first) or "down" (the commit fails after the
    gateway step and storage stays unavailable, so reading the approval again
    fails too). approve_error makes re-pinning fail.
    """

    def __init__(
        self,
        owned=True,
        key_choice="none",
        revision=1,
        fail=None,
        approve_error=None,
        in_use=(),
        late_in_use=(),
    ):
        # in_use: admin-changed levels seen before removal starts.
        # late_in_use: levels changed to this model after that first check,
        # found again under the settings lock.
        self.in_use, self.late_in_use = list(in_use), list(late_in_use)
        self.fail = fail
        self.approve_error = approve_error
        self.storage_down = False
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
        if self.storage_down:
            raise StorageUnavailable("Keeplane storage is unavailable")
        return self.approval if model_id == MODEL else None

    def routing_uses(self, model_id):
        return list(self.in_use) if model_id == MODEL else []

    def remove(self, model_id, actor, remove_from_gateway=None):
        if self.late_in_use:
            raise ModelInUse(model_id, self.late_in_use)
        if self.fail == "write":
            raise StorageUnavailable("Keeplane storage is unavailable")
        if self.fail == "gone":
            self.approval = None
            return False
        if remove_from_gateway:
            status, result = remove_from_gateway()
            if status != 200:
                raise GatewayRemovalFailed(status, result)
        if self.fail == "landed":
            self.approval = None
        if self.fail == "changed":
            self.approval = dict(self.approval, approved_classes=["Internal"])
        if self.fail == "down":
            self.storage_down = True
        if self.fail in ("commit", "landed", "changed", "down"):
            raise StorageUnavailable("Keeplane storage is unavailable")
        self.removals.append((model_id, actor, bool(remove_from_gateway)))
        self.approval = None
        return True

    def approve(self, model_id, classes, revision, actor, **options):
        if self.approve_error:
            raise self.approve_error
        if self.storage_down:
            raise StorageUnavailable("Keeplane storage is unavailable")
        self.repinned.append((model_id, classes, revision, actor, options))
        self.approval = dict(self.approval, gateway_fingerprint=revision)


class Gateway:
    def __init__(
        self,
        resources=None,
        delete_status=200,
        restore_status=200,
        read_after_restore=200,
        restored_value=None,
    ):
        self.registry = [RESOURCE] if resources is None else resources
        self.delete_status = delete_status
        self.restore_status = restore_status
        # How the gateway answers the readback after a write back, and what
        # it then holds (None: exactly the definition written back).
        self.read_after_restore = read_after_restore
        self.restored_value = restored_value
        self.read_count = 0
        self.deletions = []
        self.restores = []

    def resources(self):
        self.read_count += 1
        if self.restores and self.read_after_restore != 200:
            return self.read_after_restore, {"error": "Gateway unavailable"}
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
        kept = value if self.restored_value is None else self.restored_value
        self.registry = self.registry + [
            {"id": MODEL, "revision": 7, "value": json.loads(json.dumps(kept))}
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

    def assert_not_recorded(self, result, outcome):
        self.assertEqual(
            result, {"error": "Keeplane couldn't record the removal. " + outcome}
        )

    def test_mr_14_personal_key_restore_asks_developers_to_check_keys(self):
        catalog, gateway = Catalog(key_choice="personal", fail="commit"), Gateway()
        status, result = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual(status, 503)
        self.assert_not_recorded(
            result,
            "The model is back in the gateway. Developers using their own "
            "provider keys for it must check them again.",
        )
        self.assertEqual(len(catalog.repinned), 1)

    def test_mr_15_commit_that_landed_is_reported_as_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / ("key-" + "a" * 32)
            key.write_text("private-fixture-key")
            resource = json.loads(json.dumps(RESOURCE))
            resource["value"]["auth"] = {"key": {"value": {"file": str(key)}}}
            catalog = Catalog(key_choice="shared", fail="landed")
            catalog.approval["gateway_fingerprint"] = fingerprint(MODEL, [resource])
            gateway = Gateway([resource])
            status, result = remove_model_setup(
                MODEL, ACTOR, catalog, gateway, None, directory
            )
            self.assertEqual(
                (status, result),
                (200, {"removed_from_keeplane": True, "gateway_model_preserved": False}),
            )
            self.assertEqual((gateway.restores, catalog.repinned), ([], []))
            self.assertFalse(key.exists())

    def test_mr_16_setup_changed_after_failed_commit_is_not_overwritten(self):
        catalog, gateway = Catalog(fail="changed"), Gateway()
        status, result = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual(status, 503)
        self.assert_not_recorded(
            result, "The model may be missing from the gateway; check Models."
        )
        self.assertEqual((gateway.restores, catalog.repinned), ([], []))
        self.assertEqual(catalog.approval["approved_classes"], ["Internal"])

    def test_mr_17_unconfirmed_write_back_asks_admin_to_check_setup(self):
        changed = dict(RESOURCE["value"], params={"model": "other"})
        cases = {
            "readback fails": (Catalog(fail="commit"), Gateway(read_after_restore=503)),
            "definition differs": (
                Catalog(fail="commit"),
                Gateway(restored_value=changed),
            ),
            "re-pin refused": (
                Catalog(fail="commit", approve_error=ValueError("Choose valid data classes")),
                Gateway(),
            ),
            "re-pin storage fails": (
                Catalog(
                    fail="commit",
                    approve_error=StorageUnavailable("Keeplane storage is unavailable"),
                ),
                Gateway(),
            ),
        }
        for name, (catalog, gateway) in cases.items():
            with self.subTest(name):
                previous = catalog.approval
                status, result = remove_model_setup(
                    MODEL, ACTOR, catalog, gateway, None, ""
                )
                self.assertEqual(status, 503)
                self.assert_not_recorded(
                    result,
                    "The model is back in the gateway; check its setup in Models.",
                )
                self.assertEqual(len(gateway.restores), 1)
                self.assertEqual(catalog.repinned, [])
                self.assertIs(catalog.approval, previous)

    def test_mr_18_removal_already_done_by_another_request(self):
        catalog, gateway = Catalog(fail="gone"), Gateway()
        status, result = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual((status, result), (404, {"error": "Model setup not found"}))
        self.assertEqual((gateway.deletions, gateway.restores), ([], []))

    def test_mr_19_failed_reread_still_writes_the_model_back(self):
        catalog, gateway = Catalog(fail="down"), Gateway()
        previous = catalog.approval
        status, result = remove_model_setup(MODEL, ACTOR, catalog, gateway, None, "")
        self.assertEqual(status, 503)
        self.assert_not_recorded(
            result, "The model is back in the gateway; check its setup in Models."
        )
        self.assertEqual(gateway.restores, [RESOURCE["value"]])
        self.assertEqual(
            [item["value"] for item in gateway.registry], [RESOURCE["value"]]
        )
        self.assertEqual(catalog.repinned, [])
        self.assertIs(catalog.approval, previous)


if __name__ == "__main__":
    unittest.main(verbosity=2)

    def test_mr_20_model_used_by_an_admin_changed_level_is_kept(self):
        for owned in (True, False):
            with self.subTest(owned=owned):
                catalog = Catalog(owned=owned, in_use=["Simple", "Complex"])
                gateway = Gateway()
                status, result = remove_model_setup(
                    MODEL, ACTOR, catalog, gateway, None, ""
                )
                self.assertEqual(status, 409)
                self.assertEqual(
                    result["in_use"], {"levels": ["Simple", "Complex"], "persona_rules": []}
                )
                self.assertEqual(
                    result["error"],
                    f"{MODEL} is still in use. "
                    "Move these to another model first, then remove it.",
                )
                self.assertEqual(catalog.removals, [])
                self.assertIsNotNone(catalog.approval)
                self.assertEqual((gateway.read_count, gateway.deletions), (0, []))

    def test_mr_21_level_changed_during_removal_still_keeps_the_model(self):
        for owned in (True, False):
            with self.subTest(owned=owned):
                catalog, gateway = Catalog(owned=owned, late_in_use=["Standard"]), Gateway()
                status, result = remove_model_setup(
                    MODEL, ACTOR, catalog, gateway, None, ""
                )
                self.assertEqual(
                    (status, result["in_use"]["levels"]), (409, ["Standard"])
                )
                self.assertEqual((catalog.removals, gateway.deletions), ([], []))
                self.assertIsNotNone(catalog.approval)
