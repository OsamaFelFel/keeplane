from django.urls import path

from . import views

urlpatterns = [
    path("api/projects", views.projects),
    path("api/projects/<uuid:project_id>/class", views.project_class),
]
