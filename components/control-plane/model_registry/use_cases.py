"""Assemble model use cases and resolve their effective setup state."""

import os
from common.api import (
    CATALOG,
    DATA_CLASSES,
    MODEL_GATEWAY,
    MODEL_GATEWAY_COPIES,
    RUNNER_URLS,
)
from .registration import ModelManagement
from .listing import list_models


def model_management(user):
    return ModelManagement(
        CATALOG,
        DATA_CLASSES,
        MODEL_GATEWAY,
        (user["id"], user["username"]),
        os.environ.get("GATEWAY_MODE", "managed"),
        os.environ.get("GATEWAY_FILE_CONFIG"),
        os.environ.get("PROVIDER_KEY_DIR", ""),
        RUNNER_URLS,
        {
            "openai": os.environ.get("PREVIEW_OPENAI_BASE_URL", ""),
            "anthropic": os.environ.get("PREVIEW_ANTHROPIC_BASE_URL", ""),
        },
        os.environ.get("PREVIEW_PROVIDER_KEY", ""),
        copies=MODEL_GATEWAY_COPIES,
    )


def effective_model_ids():
    status, listing = list_models(
        MODEL_GATEWAY.models,
        MODEL_GATEWAY.resources,
        CATALOG,
        os.environ.get("GATEWAY_FILE_CONFIG"),
        RUNNER_URLS,
    )
    if status != 200:
        return status, listing, None
    return 200, {}, {item["id"] for item in listing["models"] if item.get("approved")}
