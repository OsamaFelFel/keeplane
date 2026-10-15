"""Focused durable audit-store checks without the Docker preview."""

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components/control-plane"))
from audit import AuditStore
from data_classes import DataClassStore
from model_catalog import ModelCatalog


class AuditStoreChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name) / "settings.db"
        self.audit = AuditStore(path)
        self.models = ModelCatalog(path, self.audit)
        self.classes = DataClassStore(path, self.audit)
        self.classes.set_enabled(True)
        self.actor = ("subject-1", "first-admin")

    def tearDown(self):
        self.directory.cleanup()

    def test_off_by_default_and_independent_switches(self):
        self.assertEqual(self.audit.options(), {"settings": False, "held_requests": False,
                                                "model_answers": False})
        self.models.approve("mock", ["Public"], "fingerprint", self.actor)
        self.assertEqual(self.audit.records()["total"], 0)
        self.audit.set_option("settings", True)
        self.assertEqual(self.audit.options(), {"settings": True, "held_requests": False,
                                                "model_answers": False})
        self.assertFalse(self.audit.record("held_requests", *self.actor, "held"))
        self.assertEqual(self.audit.records()["total"], 0)

    def test_settings_are_recorded_atomically_with_actor_and_noop_skipped(self):
        self.audit.set_option("settings", True)
        self.models.approve("mock", ["Public"], "fingerprint", self.actor)
        self.models.approve("mock", ["Public"], "fingerprint", self.actor)
        item = self.classes.add({"name": "Trial", "approved_model_ids": ["mock"]},
                                {"mock"}, self.actor)
        self.classes.edit(item["id"], {"name": "Trial", "approved_model_ids": ["mock"]},
                          {"mock"}, self.actor)
        self.classes.edit(item["id"], {"name": "Trial renamed", "approved_model_ids": ["mock"]},
                          {"mock"}, self.actor)
        self.classes.remove(item["id"], self.actor)
        found = self.audit.records(search="Trial")
        self.assertEqual(found["total"], 3)
        self.assertEqual([row["who"] for row in found["records"]], ["first-admin"] * 3)
        self.assertTrue(all(row["when"].endswith("+00:00") for row in found["records"]))
        self.assertEqual(self.audit.records(kind="settings")["total"], 4)
        self.assertEqual(self.audit.records(kind="model_answers")["total"], 0)

    def test_data_class_mode_changes_are_recorded_without_noops(self):
        self.audit.set_option("settings", True)
        self.classes.set_enabled(True, self.actor)
        self.assertEqual(self.audit.records(kind="settings")["total"], 0)
        self.classes.set_enabled(False, self.actor)
        self.classes.set_enabled(True, self.actor)
        records = self.audit.records(kind="settings")["records"]
        self.assertEqual([item["what"] for item in records],
                         ["Turned data classes on", "Turned data classes off"])

    def test_literal_search_and_paging(self):
        self.audit.set_option("settings", True)
        for index in range(30):
            self.audit.record("settings", *self.actor, f"Item {index:02d} 100%")
        self.assertEqual(len(self.audit.records(page=1)["records"]), 25)
        self.assertEqual(len(self.audit.records(page=2)["records"]), 5)
        self.assertEqual(self.audit.records(search="100%")["total"], 30)
        self.assertEqual(self.audit.records(search="100_")["total"], 0)
        self.assertEqual(self.audit.records(search="Item 29")["total"], 1)


if __name__ == "__main__":
    unittest.main()
