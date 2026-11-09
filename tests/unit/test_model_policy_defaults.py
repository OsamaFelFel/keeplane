"""The model policy's reading of a missing data-class settings row (issue #249)."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from model_registry import policy as module
from model_registry.fingerprints import fingerprint
from model_registry.policy import DjangoModelPolicy, ModelPolicyUnavailable

RESOURCES = [{"id": "gateway-model", "revision": 1}]


class Rows:
    """Stand-in for a manager: each locked settings read returns the next row."""

    def __init__(self, reads=(), approvals=()):
        self.reads, self.approvals = list(reads), list(approvals)
        self.settings_reads = 0

    def select_for_update(self):
        return self

    def filter(self, **kwargs):
        if "pk__in" in kwargs:
            return [row for row in self.approvals if row.pk in kwargs["pk__in"]]
        return self

    def first(self):
        self.settings_reads += 1
        return self.reads.pop(0) if self.reads else None

    def exists(self):
        return bool(self.approvals)


def approval(classes=()):
    return SimpleNamespace(
        pk="gateway-model",
        approved_classes=list(classes),
        key_choice="shared",
        gateway_fingerprint=fingerprint("gateway-model", RESOURCES),
    )


@pytest.fixture
def stored(monkeypatch):
    def use(reads=(), approvals=()):
        rows = Rows(reads, approvals)
        monkeypatch.setattr(module, "Settings", SimpleNamespace(objects=rows))
        monkeypatch.setattr(module, "ModelApproval", SimpleNamespace(objects=rows))
        monkeypatch.setattr(module, "transaction", SimpleNamespace(atomic=nullcontext))
        monkeypatch.setattr(module, "connection", SimpleNamespace(vendor="sqlite"))
        gateway = SimpleNamespace(
            models=lambda: (200, {"data": [{"id": "gateway-model"}]}),
            resources=lambda: (200, {"resources": RESOURCES}),
        )
        return DjangoModelPolicy(gateway), rows

    return use


def test_mpd_01_no_row_and_no_approval_is_the_off_default_with_no_model(stored):
    service, rows = stored()
    held = SimpleNamespace(held=True)
    assert service.eligibility("project", held) == (frozenset(), None)
    assert rows.settings_reads == 1
    assert service.eligible_model_ids("project") == frozenset()


def test_mpd_02_no_row_with_approvals_is_lost_policy_and_fails_closed(stored):
    service, rows = stored(approvals=[approval()])
    with pytest.raises(ModelPolicyUnavailable):
        service.eligible_model_ids("project")
    assert rows.settings_reads == 2


def test_mpd_03_a_first_write_seen_on_the_re_read_applies_its_stored_policy(stored):
    saved = SimpleNamespace(classes_enabled=False, detection_enabled=False)
    service, rows = stored(reads=[None, saved], approvals=[approval()])
    assert service.eligible_model_ids("project") == {"gateway-model"}
    assert rows.settings_reads == 2


def test_mpd_04_a_stored_row_is_read_once_and_used(stored):
    saved = SimpleNamespace(classes_enabled=False, detection_enabled=False)
    service, rows = stored(reads=[saved], approvals=[approval()])
    assert service.eligible_model_ids("project") == {"gateway-model"}
    assert rows.settings_reads == 1
