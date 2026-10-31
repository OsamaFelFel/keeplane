"""Account transport, using the local account use cases during cutover."""

import os

from rest_framework.decorators import api_view
from rest_framework.response import Response
from .use_cases import model_management

from audit.contracts import AuditError
from accounts.contracts import IdentityError
from common.errors import StorageUnavailable
from model_registry.chat import ask_model
from model_registry.levels import LevelError, complexity_levels
from model_registry.listing import list_models
from model_registry.removal import remove_model_setup
from integrations.runners import local_runner


from common.api import CATALOG, MODEL_GATEWAY, RUNNER_URLS, failure, admin, action_error


@api_view(["GET", "POST"])
def models(request):
    user, denied = admin(request)
    if denied:
        return denied
    if request.method == "POST":
        denied = action_error(request)
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return failure(400, "Enter a model request")
        status, body = model_management(user).add(request.data)
        return Response(body, status=status)
    try:
        status, listing = list_models(
            MODEL_GATEWAY.models,
            MODEL_GATEWAY.resources,
            CATALOG,
            os.environ.get("GATEWAY_FILE_CONFIG"),
            RUNNER_URLS,
        )
        if status == 200:
            listing["levels"] = complexity_levels(CATALOG, set_up_ids(listing))
        return Response(listing, status=status)
    except StorageUnavailable:
        return failure(503, "Keeplane settings storage is unavailable")


def set_up_ids(listing):
    """Models set up in Keeplane with their current gateway definition."""
    return [item["id"] for item in listing["models"] if item.get("approved")]


@api_view(["POST"])
def complexity_level(request, level):
    """Change a level's model, or with a null model_id go back to Keeplane's pick."""
    user, denied = admin(request)
    if denied:
        return denied
    denied = action_error(request)
    if denied:
        return denied
    if set(request.data) != {"model_id"}:
        return failure(400, "Choose a model or Keeplane's pick")
    try:
        status, listing = list_models(
            MODEL_GATEWAY.models,
            MODEL_GATEWAY.resources,
            CATALOG,
            os.environ.get("GATEWAY_FILE_CONFIG"),
            RUNNER_URLS,
        )
        if status != 200:
            return Response(listing, status=status)
        candidates = set_up_ids(listing)
        CATALOG.change_level(
            level,
            request.data["model_id"],
            candidates,
            (user["id"], user["username"]),
        )
        return Response({"levels": complexity_levels(CATALOG, candidates)})
    except LevelError as error:
        return failure(error.status, error.message)
    except (IdentityError, AuditError) as error:
        return failure(error.status, error.message)
    except StorageUnavailable:
        return failure(503, "Keeplane settings storage is unavailable")


@api_view(["POST", "DELETE"])
def model_setup(request, model_id):
    user, denied = admin(request)
    if denied:
        return denied
    denied = action_error(request)
    if denied:
        return denied
    if request.method == "POST":
        if not isinstance(request.data, dict):
            return failure(400, "Enter a model setup request")
        status, body = model_management(user).setup(model_id, request.data)
        return Response(body, status=status)
    try:
        status, result = remove_model_setup(
            model_id,
            (user["id"], user["username"]),
            CATALOG,
            MODEL_GATEWAY,
            os.environ.get("GATEWAY_FILE_CONFIG"),
            os.environ.get("PROVIDER_KEY_DIR", ""),
        )
        return Response(result, status=status)
    except (IdentityError, AuditError) as error:
        return failure(error.status, error.message)
    except StorageUnavailable:
        return failure(503, "Keeplane settings storage is unavailable")


@api_view(["POST"])
def runner_models(request):
    _, denied = admin(request)
    if denied:
        return denied
    if not isinstance(request.data, dict):
        return failure(400, "Enter a runner address")
    status, body = local_runner(request.data.get("address"), RUNNER_URLS)
    return Response(body, status=status)


@api_view(["POST"])
def ask(request):
    _, denied = admin(request)
    if denied:
        return denied
    if not isinstance(request.data, dict):
        return failure(400, "Enter a model request")
    try:
        status, body = ask_model(
            request.data, CATALOG, MODEL_GATEWAY, os.environ.get("GATEWAY_FILE_CONFIG")
        )
        return Response(body, status=status)
    except StorageUnavailable:
        return failure(503, "Keeplane settings storage is unavailable")
