"""Supported Audit event kinds and validation errors."""

KINDS = ("settings", "held_requests", "model_answers")


BREAK_GLASS_KIND = "break_glass_sign_ins"


RECORD_KINDS = (*KINDS, BREAK_GLASS_KIND)


class AuditError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message
