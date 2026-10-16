"""Per-model snapshots for future publication; the installed gate is unchanged."""

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass

from .applied import applied_fingerprint, read_applied
from .runtime_config import RuntimeInstallationUnavailable
from .runtime_readback import require_applied_models

MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
PREFIX = "llm:model:"


@dataclass(frozen=True)
class ModelServingBinding:
    model_id: str
    raw_fingerprint: str
    file_digest: str
    effective_digest: str
    applied_digest: str


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not MODEL_ID.fullmatch(value):
        raise ValueError()
    return value


def model_identifier(value):
    result = identifier(value["id"])
    if value["name"] != result or ("matches" in value and value["matches"] != []):
        raise ValueError()
    return result


def relevant_target(target, model_id):
    """Exclude only an exact backend target belonging to a different model."""
    if not isinstance(target, dict) or len(target) != 1:
        raise ValueError()
    kind, value = next(iter(target.items()))
    if kind == "backend":
        if set(value) != {"backend"}:
            raise ValueError()
        ref = value["backend"]
        if set(ref) != {"name", "namespace"} or not isinstance(ref["name"], str):
            raise ValueError()
        if ref["namespace"] != "":
            raise ValueError()
        if ref["name"].startswith(PREFIX):
            return identifier(ref["name"][len(PREFIX) :]) == model_id
        return True
    allowed = {
        "gateway": {"gatewayName", "gatewayNamespace", "listenerName", "port"},
        "route": {"name", "namespace", "ruleName", "kind"},
        "listenerSet": {"name", "namespace", "section"},
    }
    if kind not in allowed or not isinstance(value, dict) or set(value) - allowed[kind]:
        raise ValueError()
    return True


def policies_for_model(rows, model_id):
    if not isinstance(rows, list):
        raise TypeError()
    keys, result = set(), []
    for row in rows:
        key = row.get("key", digest(row.get("name")))
        # Unnamed compiled gateway policies have stable native keys. Unnamed
        # file policies cannot be excluded without an index-lifetime contract.
        if key in keys or ("key" not in row and not row.get("name")):
            raise ValueError()
        keys.add(key)
        if relevant_target(row["target"], model_id):
            result.append(row)
    return result


def project_config(config, model_id):
    result = deepcopy(config)
    section = result["llm"]
    if section.get("virtualModels", []) != []:
        raise ValueError()
    models = section["models"]
    identifiers = [model_identifier(model) for model in models]
    if len(set(identifiers)) != len(models):
        raise ValueError()
    section["models"] = [model for model in models if model["id"] == model_id]
    if "policies" in result:
        result["policies"] = policies_for_model(result["policies"], model_id)
    return result


def project_applied(value, model_id):
    result = deepcopy(value)
    retained, router_count, names = [], 0, set()
    for row in result["backends"]:
        backend = row["backend"]
        if len(backend) != 1:
            raise ValueError()
        kind, target = next(iter(backend.items()))
        name = (kind, target["namespace"], target["name"])
        if name in names:
            raise ValueError()
        names.add(name)
        if kind == "llmRouter":
            if target["name"] != "llm:router" or target["namespace"] != "":
                raise ValueError()
            router_count += 1
            router = target["target"]
            if router["virtualModels"] != []:
                raise ValueError()
            routes, seen = [], set()
            for route in router["models"]:
                current = identifier(route["id"])
                if (
                    current in seen
                    or route["name"] != current
                    or route["headerMatches"] != []
                    or route["visibility"] != "public"
                    or set(route)
                    != {
                        "id",
                        "name",
                        "created",
                        "visibility",
                        "headerMatches",
                        "backend",
                        "policies",
                        "backendPolicies",
                    }
                    or route["backendPolicies"] != []
                    or type(route["backend"]["weight"]) is not int
                    or route["backend"]
                    != {"weight": 1, "backend": "/" + PREFIX + current}
                ):
                    raise ValueError()
                seen.add(current)
                if current == model_id:
                    routes.append(route)
            if len(routes) != 1:
                raise ValueError()
            router["models"] = routes
        elif kind == "ai":
            if target["namespace"] != "" or not target["name"].startswith(PREFIX):
                raise ValueError()
            current = identifier(target["name"][len(PREFIX) :])
            if current != model_id:
                continue
        elif kind == "internal":
            # The maintained management UI uses this native admin reference.
            # Keep it and every attached field; no arbitrary internal target.
            if target != {"name": "ui", "namespace": "", "target": "forward"}:
                raise ValueError()
        elif kind != "host":
            raise ValueError()
        retained.append(row)
    if router_count != 1:
        raise ValueError()
    result["backends"] = retained
    result["policies"] = policies_for_model(result["policies"], model_id)
    return result


def require_backend_references(value, retained):
    """Named route/callback/key-exchange dependencies must remain fully bound.

    LocalBackend and SimpleBackendReference use the same `backend` field. Bare
    local names compile to `/name`; namespaced keys already contain a slash.
    This only refuses unsupported references; it never removes another field.
    """
    if isinstance(value, dict):
        reference = value.get("backend")
        if isinstance(reference, str):
            key = reference if "/" in reference else "/" + reference
            if key not in retained:
                raise ValueError()
        for row in value.values():
            require_backend_references(row, retained)
    elif isinstance(value, list):
        for row in value:
            require_backend_references(row, retained)


def model_serving_binding(
    model_id, key_choice, file_config, effective_config, resources, applied
):
    """Bind a declared model and shared wiring, never authorize or activate it.

    The first reader supports stable IDs and direct concrete models only. It
    does not claim a lease across reads, attest loaded key bytes or accept a
    caller's digest as authority. A publisher must compare a trusted binding.
    """
    try:
        identifier(model_id)
        if key_choice not in ("none", "shared", "personal"):
            raise ValueError()
        ids = []
        for row in resources:
            if (
                row["kind"] != "llm.model"
                or type(row["revision"]) is not int
                or row["revision"] < 1
            ):
                raise ValueError()
            current = model_identifier(row["value"])
            if row["id"] != current:
                raise ValueError()
            ids.append(current)
        if len(set(ids)) != len(ids) or model_id not in ids:
            raise ValueError()
        selected = resources[ids.index(model_id)]
        expected = deepcopy(file_config)
        expected["llm"]["models"].append(deepcopy(selected["value"]))
        projected_file = project_config(file_config, model_id)
        projected_effective = project_config(effective_config, model_id)
        if digest(project_config(expected, model_id)) != digest(projected_effective):
            raise ValueError()
        require_applied_models(
            applied,
            resources,
            {model_id: {"key_choice": key_choice}},
            {model_id: PREFIX + model_id},
        )
        projected_applied = project_applied(applied, model_id)
        retained = set()
        for row in projected_applied["backends"]:
            target = next(iter(row["backend"].values()))
            if not isinstance(target["namespace"], str) or not isinstance(
                target["name"], str
            ):
                raise TypeError()
            retained.add(target["namespace"] + "/" + target["name"])
        for value in (projected_file, projected_effective, projected_applied):
            require_backend_references(value, retained)
        return ModelServingBinding(
            model_id,
            digest({"value": selected["value"], "revision": selected["revision"]}),
            digest(projected_file),
            digest(projected_effective),
            applied_fingerprint(projected_applied),
        )
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise RuntimeInstallationUnavailable(
            "The model serving binding is unavailable"
        ) from None


def read_model_binding(gateway, model_id, key_choice):
    """Read this configured copy only; no redirect target or URL comes from clients."""
    try:
        snapshots = []
        for path in ("/api/config", "/api/config/effective", "/api/config/resources"):
            status, value = gateway.request(path, timeout=5, connection_retries=0)
            if status != 200 or not isinstance(value, dict):
                raise ValueError()
            snapshots.append(value)
        return model_serving_binding(
            model_id,
            key_choice,
            snapshots[0],
            snapshots[1],
            snapshots[2]["resources"],
            read_applied(gateway),
        )
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise RuntimeInstallationUnavailable(
            "The model serving binding is unavailable"
        ) from None
