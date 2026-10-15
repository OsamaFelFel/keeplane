"""Class and approval invariants in Django ORM transactions."""

from data_classes.contracts import DataClassError
from data_classes.models import ProjectClass


def expect_conflict(action):
    try:
        action()
    except DataClassError as error:
        assert error.status == 409
    else:
        raise AssertionError("Expected an in-use class conflict")


def test_class_and_model_boundaries(domain_services):
    models = domain_services.catalog
    classes = domain_services.classes
    assert classes.enabled() is False
    assert classes.list() == []
    classes.set_enabled(True)
    assert [item["name"] for item in classes.list()] == [
        "Public",
        "Internal",
        "Confidential",
    ]
    models.approve("fixture", ["Public"], "tested-definition")
    created = classes.add({"name": "Private", "approved_model_ids": ["fixture"]})
    assert set(models.get("fixture")["approved_classes"]) == {"Public", "Private"}
    ProjectClass.objects.create(
        project_id="example-project", data_class_id=created["id"]
    )
    expect_conflict(lambda: classes.remove(created["id"]))
    assert classes.list()[-1]["project_count"] == 1
    classes.edit(
        created["id"], {"name": "Restricted", "approved_model_ids": ["fixture"]}
    )
    assert set(models.get("fixture")["approved_classes"]) == {"Public", "Restricted"}
    ProjectClass.objects.filter(project_id="example-project").delete()
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
    print(
        "PASS: classes start off, opt in seeds starters, and model setup survives lost class approvals"
    )
