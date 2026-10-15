"""Admin project reads; usage registration remains an authenticated internal service."""

from urllib.parse import parse_qs

from common.api import admin, failure
from rest_framework.decorators import api_view
from rest_framework.response import Response

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
