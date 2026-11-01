"""Data-class validation errors and starter names."""

STARTERS = (
    ("public", "Public"),
    ("internal", "Internal"),
    ("confidential", "Confidential"),
)

# D108: detected requests are handled as Confidential unless the admin changes it.
DETECTION_DEFAULT = "confidential"
NOT_INSTALLED = "Personal-data detection isn't installed. Install it, then turn this on."
CLASS_IN_USE = (
    "Personal-data detection still uses this class. Choose another class under "
    "Handle it as first, then remove it."
)


class DataClassError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message
