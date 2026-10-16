"""Protected, read-only model catalog for developer clients."""

import os
import uuid

from django.views.decorators.cache import never_cache
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.authentication import RuntimeSessionAuthentication, runtime_bearer_only
from accounts.cli_credentials import RuntimeIdentity
from accounts.models import User
from django.db import transaction
from common.api import IDENTITY, MODEL_GATEWAY
from common.errors import StorageUnavailable
from projects.access import organization_project_access
from projects.services import DjangoProjectStore, ProjectError
from .policy import DjangoModelPolicy, ModelPolicyUnavailable


def model_policy():
    return DjangoModelPolicy(MODEL_GATEWAY, os.environ.get("GATEWAY_FILE_CONFIG"))


@never_cache
@api_view(["GET"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def project_models(request, project_id):
    try:
        project_id = str(uuid.UUID(project_id))
    except (ValueError, TypeError, AttributeError):
        return Response({"error": "This project is unavailable"}, status=403)
    if not organization_project_access(str(request.user.pk), project_id):
        return Response({"error": "This project is unavailable"}, status=403)
    try:
        models = model_policy().eligible_model_ids(project_id)
    except (ModelPolicyUnavailable, StorageUnavailable):
        return Response({"error": "Model policy is unavailable"}, status=503)
    return Response(
        {"project_id": project_id, "models": [{"id": name} for name in sorted(models)]}
    )


@never_cache
@runtime_bearer_only
@api_view(["GET", "DELETE"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def session(request):
    """Return the current account or revoke this request's exact credential."""
    if request.method == "GET":
        return Response(
            {
                "id": str(request.user.pk),
                "username": request.user.username,
                "role": request.user.role,
            }
        )
    if request.body:
        return Response({"error": "Send an empty logout request"}, status=400)
    with transaction.atomic():
        User.objects.select_for_update().filter(pk=request.user.pk).first()
        RuntimeSessionAuthentication().authenticate(request)
        RuntimeIdentity(IDENTITY).logout(request.auth)
    return Response(status=204)


@never_cache
@runtime_bearer_only
@api_view(["POST"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def register_project_use(request):
    body = request.data
    if not isinstance(body, dict) or set(body) != {"project_id", "name"}:
        return Response({"error": "Send only a project ID and name"}, status=400)
    try:
        project = DjangoProjectStore().register_use(
            str(request.user.pk), body["project_id"], body["name"]
        )
    except ProjectError as error:
        return Response({"error": error.message}, status=error.status)
    return Response({"project_id": project["id"], "name": project["name"]})
