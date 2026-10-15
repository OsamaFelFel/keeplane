"""Audit database records."""

from django.db import models


class AuditOption(models.Model):
    kind = models.CharField(max_length=32, primary_key=True)
    enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_auditoption"


class AuditRecord(models.Model):
    kind = models.CharField(max_length=32)
    happened_at = models.DateTimeField(auto_now_add=True)
    actor_id = models.CharField(max_length=64)
    actor_name = models.CharField(max_length=64)
    description = models.TextField()

    class Meta:
        db_table = "accounts_auditrecord"
        indexes = [models.Index(fields=["kind", "-id"], name="audit_kind_recent")]
