"""Mandatory and opt-in Audit records share the domain transaction."""

from django.db import transaction
from django.db.models import Q

from audit import AuditError, BREAK_GLASS_KIND, KINDS, RECORD_KINDS
from .models import AuditOption, AuditRecord
from .storage import settings_change, storage_service


@storage_service
class DjangoAuditStore:
    def options(self):
        rows = dict(AuditOption.objects.values_list("kind", "enabled"))
        return {kind: rows.get(kind, False) for kind in KINDS}

    def set_option(self, kind, enabled):
        if kind not in KINDS or not isinstance(enabled, bool):
            raise AuditError(400, "Choose a valid record kind and on or off")
        with settings_change():
            AuditOption.objects.update_or_create(kind=kind, defaults={"enabled": enabled})
        return self.options()

    def record_in_transaction(self, connection, kind, actor_id, actor_name, description):
        if kind not in KINDS:
            raise ValueError("Unknown audit record kind")
        if not AuditOption.objects.filter(pk=kind, enabled=True).exists():
            return False
        AuditRecord.objects.create(kind=kind, actor_id=str(actor_id), actor_name=actor_name, description=description)
        return True

    def record(self, kind, actor_id, actor_name, description):
        with transaction.atomic():
            return self.record_in_transaction(None, kind, actor_id, actor_name, description)

    def record_break_glass(self, user):
        AuditRecord.objects.create(kind=BREAK_GLASS_KIND, actor_id=user["id"],
                                   actor_name=user["username"], description="Break-glass admin signed in.")

    def records(self, kind="all", search="", page=1, page_size=25):
        if kind != "all" and kind not in RECORD_KINDS:
            raise AuditError(400, "Choose a valid record kind")
        if not isinstance(search, str) or len(search) > 80:
            raise AuditError(400, "Search must be at most 80 characters")
        if not isinstance(page, int) or page < 1 or page > 10000:
            raise AuditError(400, "Page must be between 1 and 10000")
        if not isinstance(page_size, int) or page_size < 1 or page_size > 50:
            raise AuditError(400, "Page size must be between 1 and 50")
        rows = AuditRecord.objects.all()
        if kind != "all":
            rows = rows.filter(kind=kind)
        if search:
            rows = rows.filter(Q(actor_name__icontains=search) | Q(description__icontains=search))
        total = rows.count()
        records = [{"id": row.pk, "kind": row.kind, "when": row.happened_at.isoformat(timespec="seconds"),
                    "who": row.actor_name, "what": row.description}
                   for row in rows.order_by("-id")[(page - 1) * page_size:page * page_size]]
        return {"records": records, "total": total, "page": page, "page_size": page_size,
                "has_more": page * page_size < total}
