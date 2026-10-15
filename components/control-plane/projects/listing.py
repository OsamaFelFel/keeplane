"""A bounded, searchable admin view of projects and their recorded users."""

from common.storage import storage_service
from data_classes.models import ProjectClass, Settings
from django.db.models import Prefetch
from django.db.models.functions import Lower

from .models import Project, ProjectUse
from .services import ProjectError


@storage_service
class DjangoProjectListing:
    def list(self, query):
        try:
            page = int(query.get("page", ["1"])[0])
            size = int(query.get("page_size", ["25"])[0])
        except (ValueError, TypeError, IndexError):
            raise ProjectError(400, "Page and page size must be numbers")
        if not 1 <= page <= 10000 or not 1 <= size <= 50:
            raise ProjectError(400, "Page must be positive and page size at most 50")
        search = query.get("search", [""])[0].strip()
        if len(search) > 120:
            raise ProjectError(400, "Search with up to 120 characters")
        rows = Project.objects.filter(name__icontains=search).order_by(
            Lower("name"), "id"
        )
        total = rows.count()
        start = (page - 1) * size
        uses = ProjectUse.objects.select_related("user").order_by(
            "user__username", "user_id"
        )
        projects = list(
            rows[start : start + size].prefetch_related(
                Prefetch("projectuse_set", queryset=uses, to_attr="recorded_uses")
            )
        )
        enabled = Settings.objects.filter(pk=1, classes_enabled=True).exists()
        classes = (
            {
                row.project_id: {"id": row.data_class_id, "name": row.data_class.name}
                for row in ProjectClass.objects.filter(
                    project_id__in=[str(project.pk) for project in projects]
                ).select_related("data_class")
            }
            if enabled
            else {}
        )
        result = []
        for project in projects:
            entry = {
                "id": str(project.pk),
                "name": project.name,
                # No onboarding completion is recorded by first-use registration.
                "initialized": False,
                "users": [
                    {"id": str(use.user_id), "username": use.user.username}
                    for use in project.recorded_uses
                ],
            }
            if enabled:
                entry["data_class"] = classes.get(str(project.pk))
            result.append(entry)
        return {
            "projects": result,
            "classes_enabled": enabled,
            "page": page,
            "page_size": size,
            "total": total,
            "has_more": start + size < total,
        }
