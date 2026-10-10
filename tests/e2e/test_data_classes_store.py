"""Check the local class store's project and model-approval boundaries."""

import sqlite3
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components/control-plane"))
from data_classes import DataClassError, DataClassStore
from model_catalog import ModelCatalog


def expect_conflict(action):
    try:
        action()
    except DataClassError as error:
        assert error.status == 409
    else:
        raise AssertionError("Expected an in-use class conflict")


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "catalog.sqlite3"
        models = ModelCatalog(path)
        classes = DataClassStore(path)
        assert classes.enabled() is False
        assert classes.list() == []
        classes.set_enabled(True)
        assert [item["name"] for item in classes.list()] == ["Public", "Internal", "Confidential"]
        models.approve("fixture", ["Public"], "tested-definition")
        created = classes.add({"name": "Private", "approved_model_ids": ["fixture"]})
        assert set(models.get("fixture")["approved_classes"]) == {"Public", "Private"}
        with sqlite3.connect(path) as connection:
            connection.execute("INSERT INTO project_classes VALUES (?, ?)",
                               ("example-project", created["id"]))
        expect_conflict(lambda: classes.remove(created["id"]))
        assert classes.list()[-1]["project_count"] == 1
        classes.edit(created["id"], {"name": "Restricted", "approved_model_ids": ["fixture"]})
        assert set(models.get("fixture")["approved_classes"]) == {"Public", "Restricted"}
        with sqlite3.connect(path) as connection:
            connection.execute("DELETE FROM project_classes WHERE project_id = ?", ("example-project",))
        classes.remove(created["id"])
        assert models.get("fixture")["approved_classes"] == ["Public"]
        classes.edit("public", {"name": "Public", "approved_model_ids": []})
        assert models.get("fixture")["approved_classes"] == []
        classes.set_enabled(False)
        assert not classes.enabled()
        assert models.get("fixture")["approved_classes"] == []
        models.approve("added-while-off", [], "tested-second-definition")
        classes.set_enabled(True)
        assert models.get("fixture")["approved_classes"] == []
        assert models.get("added-while-off")["approved_classes"] == []
        classes.remove("internal")
        classes.remove("confidential")
        expect_conflict(lambda: classes.remove("public"))
    print("PASS: classes start off, opt in seeds starters, and model setup survives lost class approvals")


if __name__ == "__main__":
    main()
