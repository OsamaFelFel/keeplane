"""Hourly usage totals per developer and model.

A row holds only counts. It keeps no prompt, answer, project, repository path or
time of a single request (ADR 029).
"""

from django.conf import settings
from django.db import models


class UsageTotal(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    model_id = models.CharField(max_length=256)
    # The start of the UTC hour these counts were reported in.
    hour = models.DateTimeField()
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    requests = models.BigIntegerField(default=0)
    # Requests whose answer reported no token counts; their tokens are not guessed.
    requests_without_usage = models.BigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "model_id", "hour"], name="usage_total_user_model_hour"
            )
        ]
        indexes = [models.Index(fields=["hour"], name="usage_total_hour")]
