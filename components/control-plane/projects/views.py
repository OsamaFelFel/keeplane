"""Admin project reads; usage registration remains an authenticated internal service."""

from urllib.parse import parse_qs

from common.api import AUDIT, action_error, admin, failure
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .classification import DjangoProjectClasses
from .listing import DjangoProjectListing
from .services import ProjectError


@api_view(["GET"])
def projects(request):
    _, denied = admin(request)
    if denied:
        return denied
    try:
        response = Response(
            DjangoProjectListing().list(parse_qs(request.META.get("QUERY_STRING", "")))
        )
    except ProjectError as error:
        response = failure(error.status, error.message)
    response["Cache-Control"] = "no-store"
    return response


@api_view(["GET", "PUT"])
def project_class(request, project_id):
    user, denied = admin(request)
    if denied:
        return denied
    if request.method == "GET":
        try:
            response = Response(DjangoProjectClasses(AUDIT).current(project_id))
        except ProjectError as error:
            response = failure(error.status, error.message)
        response["Cache-Control"] = "no-store"
        return response
    denied = action_error(request)
    if denied:
        return denied
    if "class_id" not in request.data:
        return failure(400, "Choose a data class or none")
    try:
        response = Response(
            DjangoProjectClasses(AUDIT).assign(
                project_id, request.data["class_id"], (user["id"], user["username"])
            )
        )
    except ProjectError as error:
        response = failure(error.status, error.message)
    response["Cache-Control"] = "no-store"
    return response
