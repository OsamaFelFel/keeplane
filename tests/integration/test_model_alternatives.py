"""Spec 004 ST16: list what a developer can switch to; never switch for them."""

import pytest
from model_registry.fingerprints import fingerprint
from model_registry.models import ModelApproval

from tests.integration.test_installed_personal_runtime import KEY
from tests.integration.test_installed_runtime import send as entry
from tests.integration.test_model_choice import choice, shared_model  # noqa: F401

pytest_plugins = ("tests.integration.test_installed_personal_runtime",)
pytestmark = pytest.mark.django_db(transaction=True)


def ask(f, model="private", token=None, query=None):
    return f.client.get(
        f"/api/runtime/projects/{f.project}/model-alternatives",
        {"model_id": model} if query is None else query,
        HTTP_AUTHORIZATION="Bearer " + (token or f.token),
    )


def listed(f, alternatives, model="private"):
    return {"project_id": f.project, "model_id": model, "alternatives": alternatives}


def test_every_other_allowed_model_is_listed_in_model_id_order(choice):  # noqa: F811
    choice.install("public")
    choice.install("outside")
    response = ask(choice)
    assert response.status_code == 200
    assert response.json() == listed(choice, ["outside", "public"])
    assert "no-store" in response["Cache-Control"]
    assert not choice.reads


def test_listing_moves_nothing_and_the_requested_model_still_works(choice):  # noqa: F811
    choice.install("public")
    assert ask(choice).json() == listed(choice, ["public"])
    assert entry(choice).status_code == 200
    # The model choice for the next task is unchanged: still the requested one.
    response = choice.client.get(
        f"/api/runtime/projects/{choice.project}/model-choice",
        {"model_id": "private"},
        HTTP_AUTHORIZATION="Bearer " + choice.token,
    )
    assert response.json()["model_id"] == "private"


def test_no_alternative_gives_an_empty_list(choice):  # noqa: F811
    assert ask(choice).json() == listed(choice, [])


@pytest.mark.parametrize(
    "candidate",
    ["other-class", "not-installed", "gateway-only", "own-key-missing", "shared-key-gone"],
)
def test_the_shared_fallback_filter_decides_what_is_listed(choice, candidate):  # noqa: F811
    f = choice
    if candidate == "other-class":
        f.install("public", classes=("Public",))
    elif candidate == "not-installed":
        f.stores.catalog.approve(
            "public", ["Confidential"], fingerprint("public", f.resources)
        )
    elif candidate == "gateway-only":
        f.declaration["models"]["outside"] = {
            "fingerprint": fingerprint("outside", f.resources),
            "key_choice": "none",
            "key_name": "",
            "key_digest": "",
        }
        f.write()
    elif candidate == "own-key-missing":
        f.install("public", key_choice="personal")
    else:
        key = shared_model(f)
        assert ask(f).json() == listed(f, ["public"])
        key.unlink()
    assert ask(f).json() == listed(f, [])


def test_the_requested_model_is_never_listed_as_its_own_alternative(choice):  # noqa: F811
    choice.install("public")
    assert ask(choice, "public").json() == listed(choice, ["private"], "public")
    # Without the developer's own key, the Personal model is not a usable alternative.
    choice.store.remove("private")
    assert ask(choice, "public").json() == listed(choice, [], "public")
    choice.store.put("private", KEY)
    assert ask(choice, "public").json() == listed(choice, ["private"], "public")


def test_a_withdrawn_class_approval_drops_the_model(choice):  # noqa: F811
    choice.install("public")
    choice.install("outside")
    ModelApproval.objects.filter(pk="outside").update(approved_classes=["Public"])
    assert ask(choice).json() == listed(choice, ["public"])


def test_response_contains_no_key_material(choice):  # noqa: F811
    choice.install("public")
    body = ask(choice).content.decode()
    for secret in (KEY, choice.fp, choice.token, str(choice.key_directory)):
        assert secret not in body


@pytest.mark.parametrize(
    "query,status",
    [
        ({}, 400),
        ({"model_id": "private", "owner_id": "forged"}, 400),
        ({"model_id": ""}, 400),
        ({"model_id": "outside"}, 403),
    ],
)
def test_invalid_or_unallowed_requests_are_refused(choice, query, status):  # noqa: F811
    assert ask(choice, query=query).status_code == status


def test_signed_out_unknown_project_and_policy_outage(choice):  # noqa: F811
    assert ask(choice, token="invalid").status_code == 401
    choice.state.status = 503
    response = ask(choice)
    assert response.status_code == 503
    assert response.json() == {"error": "Model alternatives are unavailable"}
    choice.state.status = 200
    choice.project = "not-a-project"
    assert ask(choice).status_code == 403
