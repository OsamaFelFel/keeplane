"""Data-class validation errors and starter names."""

STARTERS = (
    ("public", "Public"),
    ("internal", "Internal"),
    ("confidential", "Confidential"),
)

# D108: detected requests are handled as Confidential unless the admin changes it.
DETECTION_DEFAULT = "confidential"


class DataClassError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message
