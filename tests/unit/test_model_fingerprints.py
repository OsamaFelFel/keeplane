"""Approval fingerprints change with gateway configuration and revision."""

from model_registry.fingerprints import fingerprint


def test_fingerprint_revision_and_canonical_fields():
    original = [
        {
            "id": "shared-name",
            "revision": 1,
            "value": {
                "params": {"model": "mock-local", "baseUrl": "http://first:18080/v1"}
            },
        }
    ]
    reordered = [
        {
            "id": "shared-name",
            "revision": 1,
            "value": {
                "params": {"baseUrl": "http://first:18080/v1", "model": "mock-local"}
            },
        }
    ]
    replacement = [
        {
            "id": "shared-name",
            "revision": 1,
            "value": {
                "params": {"model": "mock-local", "baseUrl": "http://other:18080/v1"}
            },
        }
    ]
    revised = [{"id": "shared-name", "revision": 3, "value": original[0]["value"]}]
    first = fingerprint("shared-name", original)
    assert first == fingerprint("shared-name", reordered)
    assert first != fingerprint("shared-name", replacement)
    assert first != fingerprint("shared-name", revised)
    assert (
        fingerprint(
            "shared-name", [{"id": "shared-name", "value": original[0]["value"]}]
        )
        is None
    )
    assert fingerprint("missing", original) is None
