from django.urls import path
from . import runtime_views

urlpatterns = [
    path("api/runtime/projects/<str:project_id>/models", runtime_views.project_models),
]
