"""Open Source uses one organization; usage records do not grant access."""

from accounts.models import User
from .models import Project


def organization_project_access(actor_id, project_id):
    """Active organization accounts may use registered organization projects.

    Admin/developer roles control administration, not model access. Deployment
    extensions may restrict this policy; model/class checks still apply.
    """
    return User.objects.filter(pk=actor_id, is_active=True).exists() and (
        Project.objects.filter(pk=project_id).exists()
    )
