from django.urls import path
from . import views

urlpatterns = [
    path("api/models", views.models),
    path("api/models/<str:model_id>/setup", views.model_setup),
    path("api/runners/models", views.runner_models),
    path("api/ask", views.ask),
]
