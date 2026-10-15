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
from common.api import IDENTITY, MODEL_GATEWAY
from common.errors import StorageUnavailable
from projects.access import organization_project_access
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
@api_view(["DELETE"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def session(request):
    """Revoke only the exact credential authenticated for this request."""
    if request.body:
        return Response({"error": "Send an empty logout request"}, status=400)
    IDENTITY.logout(request.auth)
    return Response(status=204)
