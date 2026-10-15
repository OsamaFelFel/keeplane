from django.urls import include, path, re_path
from common import web

urlpatterns = [
    path("", include("accounts.urls")),
    path("", include("model_registry.urls")),
    path("", include("data_classes.urls")),
    path("", include("projects.urls")),
    path("", include("audit.urls")),
    path("api/status", web.gateway_status),
    path("health", web.gateway_health),
    path("health/app", web.app_health),
    path("health/ready", web.readiness),
    re_path(r"^(?:app/)?(?:assets|fonts)/(?P<asset>.+)$", web.asset),
    re_path(
        r"^(?:app/?|app/(?:models|data-classes|audit|editions)|users|models|data-classes|audit|editions|sign-in)?$",
        web.application,
    ),
]
