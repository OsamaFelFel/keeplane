"""Audit opt-in, filtering and settings transactions through Django ORM."""

from django.test import TestCase
from audit.services import DjangoAuditStore
from data_classes.services import DjangoDataClassStore
from model_registry.catalog import DjangoModelCatalog


class AuditStoreChecks(TestCase):
    def setUp(self):
        self.audit = DjangoAuditStore()
        self.models = DjangoModelCatalog(self.audit)
        self.classes = DjangoDataClassStore(self.audit)
        self.classes.set_enabled(True)
        self.actor = ("subject-1", "first-admin")

    def test_off_by_default_and_independent_switches(self):
        self.assertEqual(
            self.audit.options(),
            {"settings": False, "held_requests": False, "model_answers": False},
        )
        self.models.approve("mock", ["Public"], "fingerprint", self.actor)
        self.assertEqual(self.audit.records()["total"], 0)
        self.audit.set_option("settings", True)
        self.assertEqual(
            self.audit.options(),
            {"settings": True, "held_requests": False, "model_answers": False},
        )
        self.assertFalse(self.audit.record("held_requests", *self.actor, "held"))
        self.assertEqual(self.audit.records()["total"], 0)

    def test_settings_are_recorded_atomically_with_actor_and_noop_skipped(self):
        self.audit.set_option("settings", True)
        self.models.approve("mock", ["Public"], "fingerprint", self.actor)
        self.models.approve("mock", ["Public"], "fingerprint", self.actor)
        item = self.classes.add(
            {"name": "Trial", "approved_model_ids": ["mock"]}, {"mock"}, self.actor
        )
        self.classes.edit(
            item["id"],
            {"name": "Trial", "approved_model_ids": ["mock"]},
            {"mock"},
            self.actor,
        )
        self.classes.edit(
            item["id"],
            {"name": "Trial renamed", "approved_model_ids": ["mock"]},
            {"mock"},
            self.actor,
        )
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
        self.assertEqual(
            [item["what"] for item in records],
            ["Turned data classes on", "Turned data classes off"],
        )

    def test_literal_search_and_paging(self):
        self.audit.set_option("settings", True)
        for index in range(30):
            self.audit.record("settings", *self.actor, f"Item {index:02d} 100%")
        self.assertEqual(len(self.audit.records(page=1)["records"]), 25)
        self.assertEqual(len(self.audit.records(page=2)["records"]), 5)
        self.assertEqual(self.audit.records(search="100%")["total"], 30)
        self.assertEqual(self.audit.records(search="100_")["total"], 0)
        self.assertEqual(self.audit.records(search="Item 29")["total"], 1)


def test_mr_07_removal_and_audit_commit_together(domain_services):
    from model_registry.removal import remove_model_setup
    from tests.unit.test_model_removal import MODEL, RESOURCE, Gateway, ACTOR
    from model_registry.fingerprints import fingerprint

    s = domain_services
    s.audit.set_option("settings", True)
    s.catalog.approve(MODEL, [], fingerprint(MODEL, [RESOURCE]), ACTOR)
    status, _ = remove_model_setup(MODEL, ACTOR, s.catalog, Gateway(), None, "")
    assert status == 200 and s.catalog.get(MODEL) is None
    assert any(
        "Removed Keeplane setup" in row["what"]
        for row in s.audit.records(kind="settings")["records"]
    )
