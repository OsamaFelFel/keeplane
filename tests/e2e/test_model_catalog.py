"""Check that a changed gateway model cannot inherit an old approval."""

import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components/control-plane"))
from model_catalog import ModelCatalog, fingerprint
from data_classes import DataClassStore


def main():
    original = [{"id": "shared-name", "revision": 1, "value": {"params": {
        "model": "mock-local", "baseUrl": "http://first:18080/v1"}}}]
    reordered = [{"id": "shared-name", "revision": 1, "value": {"params": {
        "baseUrl": "http://first:18080/v1", "model": "mock-local"}}}]
    replacement = [{"id": "shared-name", "revision": 1, "value": {"params": {
        "model": "mock-local", "baseUrl": "http://other:18080/v1"}}}]
    revised = [{"id": "shared-name", "revision": 3, "value": original[0]["value"]}]
    first = fingerprint("shared-name", original)
    assert first == fingerprint("shared-name", reordered)
    assert first != fingerprint("shared-name", replacement)
    assert first != fingerprint("shared-name", revised)
    assert fingerprint("shared-name", [{"id": "shared-name", "value": original[0]["value"]}]) is None
    assert fingerprint("missing", original) is None
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / "gateway.yaml"
        config.write_text("model: first\n")
        file_first = fingerprint("local-fixture", [], config)
        config.write_text("model: second\n")
        assert file_first != fingerprint("local-fixture", [], config)
        assert fingerprint("local-fixture", [], Path(directory) / "missing.yaml") is None
        catalog = ModelCatalog(Path(directory) / "catalog.sqlite3")
        DataClassStore(Path(directory) / "catalog.sqlite3")
        catalog.approve("shared-name", ["Public"], first)
        stored = catalog.get("shared-name")
        assert stored["gateway_fingerprint"] == first
        assert stored["owned_by_keeplane"] is False
        catalog.approve("shared-name", ["Public"], first, owned_by_keeplane=True)
        assert catalog.get("shared-name")["owned_by_keeplane"] is True
        assert stored["gateway_fingerprint"] != fingerprint("shared-name", replacement)
        assert catalog.remove("shared-name")
        assert catalog.get("shared-name") is None
    print("PASS: reordered fields preserve approval; changed endpoint, revision or file configuration does not")


if __name__ == "__main__":
    main()
