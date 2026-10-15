from django.urls import path
from . import views

urlpatterns = [
    path("api/data-classes", views.data_classes),
    path("api/data-classes/mode", views.data_class_mode),
    path("api/data-classes/<str:class_id>", views.data_class_detail),
]
