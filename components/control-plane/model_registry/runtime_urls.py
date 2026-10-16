from django.urls import path

from . import runtime_callback, runtime_keys, runtime_views

urlpatterns = [
    path("internal/runtime/authorize", runtime_callback.authorize),
    path("internal/runtime/installed/entry", runtime_callback.authorize_installed),
    path(
        "internal/runtime/installed/selected",
        runtime_callback.authorize_installed,
        {"selected": True},
    ),
    path("api/runtime/projects", runtime_views.register_project_use),
    path("api/runtime/session", runtime_views.session),
    path("api/runtime/provider-keys", runtime_keys.provider_keys),
    path("api/runtime/projects/<str:project_id>/models", runtime_views.project_models),
]
