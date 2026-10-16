"""Native configuration for the opt-in, managed local runtime installation."""

import hashlib
import json
from copy import deepcopy

from .applied import private_applied_route

MARKER = "x-keeplane-installed-runtime"
PROTECTED = f'request.headers["{MARKER}"] == "1"'
OPERATOR = f'request.headers["{MARKER}"] == "operator"'


class RuntimeInstallationUnavailable(ValueError):
    pass


def model_backends(dump, model_ids):
    """Only stable explicit IDs can carry a persistent final-model overlay."""
    routers = [
        row.get("backend", {}).get("llmRouter") for row in dump.get("backends", [])
    ]
    routers = [
        row
        for row in routers
        if isinstance(row, dict)
        and row.get("name") == "llm:router"
        and row.get("namespace") == ""
    ]
    if len(routers) != 1:
        raise RuntimeInstallationUnavailable("The applied native router is unavailable")
    result = {}
    for model_id in model_ids:
        rows = [
            row
            for row in routers[0].get("target", {}).get("models", [])
            if row.get("name") == model_id
        ]
        if (
            len(rows) != 1
            or rows[0].get("headerMatches")
            or rows[0].get("id", model_id) != model_id
        ):
            raise RuntimeInstallationUnavailable("The applied model route is ambiguous")
        backend = rows[0].get("backend", {}).get("backend")
        if backend != "/llm:model:" + model_id:
            raise RuntimeInstallationUnavailable(
                "The applied model target is unsupported"
            )
        result[model_id] = backend[1:]
    if len(set(result.values())) != len(result):
        raise RuntimeInstallationUnavailable(
            "Installed models share an ambiguous target"
        )
    return result


def callback(host, path, model_expression, fingerprint=None):
    fields = (
        '{"project_id": request.headers["x-keeplane-project-id"], "model_id": '
        + model_expression
    )
    if fingerprint is not None:
        fields += ', "definition_fingerprint": ' + json.dumps(fingerprint)
    return {
        "host": host,
        "failureMode": "deny",
        "includeRequestHeaders": ["authorization", MARKER],
        "policies": {
            "backendAuth": {
                "key": {
                    "value": {"file": "/installed/callback-key"},
                    "location": {
                        "header": {
                            "name": "x-keeplane-gateway-credential",
                            "prefix": "",
                        }
                    },
                }
            }
        },
        "protocol": {
            "http": {
                "path": json.dumps(path),
                "addRequestHeaders": {
                    "content-type": '"application/json"',
                    ":method": '"POST"',
                },
                "body": fields + "}",
            }
        },
    }


def selected_callback(host, model_id, fingerprint):
    result = callback(
        host, "/internal/runtime/installed/selected", json.dumps(model_id), fingerprint
    )
    protocol = result["protocol"]["http"]
    protected_body = protocol["body"]
    operator_body = json.dumps(
        {"model_id": model_id, "definition_fingerprint": fingerprint}
    )
    # Backend-targeted conditional extAuthz is rejected by pinned native source.
    # Unconditional extAuthz supports CEL-computed paths and bodies instead.
    # A missing marker is an evaluation error, never an operator default.
    protocol["path"] = (
        f'{PROTECTED} ? "/internal/runtime/installed/selected" : '
        f'{OPERATOR} ? "/internal/runtime/installed/operator-validation" : '
        '"/internal/runtime/installed/invalid"'
    )
    protocol["body"] = (
        f"{PROTECTED} ? {protected_body} : {OPERATOR} ? {operator_body} : null"
    )
    # Native strict API-key auth removes the raw listener's Authorization header.
    # Recover only its verified CEL claim, never a client-supplied replacement.
    protocol["addRequestHeaders"]["authorization"] = (
        f'{OPERATOR} ? "Bearer " + apiKey.key.unredacted() : '
        f'{PROTECTED} ? request.headers["authorization"] : ""'
    )
    return result


def personal_exchange(host, model_id, fingerprint):
    return {
        "host": host,
        "path": "/internal/runtime/installed-provider-token",
        "cache": {"maxEntries": 0},
        "additionalParams": {
            "project_id": 'request.headers["x-keeplane-project-id"]',
            "model_id": json.dumps(model_id),
            "definition_fingerprint": json.dumps(fingerprint),
        },
        "policies": {
            "backendAuth": {
                "key": {
                    "value": {"file": "/installed/callback-key"},
                    "location": {
                        "header": {
                            "name": "x-keeplane-gateway-credential",
                            "prefix": "",
                        }
                    },
                }
            }
        },
    }


def overlay(base, models, targets, *, callback_host="app:3000", port=5000):
    if not isinstance(base, dict) or set(models) != set(targets) or not models:
        raise RuntimeInstallationUnavailable(
            "Declare exact installed models and targets"
        )
    result = deepcopy(base)
    gateway = result.get("gateways", {}).get("default", {})
    if (
        gateway.get("port") != 4000
        or gateway.get("listeners")
        or "transformations" in gateway
    ):
        raise RuntimeInstallationUnavailable(
            "The private managed listener is unsupported"
        )
    api_key = result.get("llm", {}).get("policies", {}).get("apiKey", {})
    if api_key.get("mode") != "strict" or not api_key.get("keys"):
        raise RuntimeInstallationUnavailable(
            "Private operator authentication is required"
        )
    gateway["transformations"] = {"request": {"set": {MARKER: '"operator"'}}}
    result.setdefault("routes", []).append(private_applied_route(api_key))
    if any(row.get("port") == port for row in result.get("binds", [])):
        raise RuntimeInstallationUnavailable("The protected port is already configured")
    config = result.setdefault("config", {})
    config["adminAddr"] = "127.0.0.1:15000"
    config["sensitiveHeaders"] = sorted(
        set(config.get("sensitiveHeaders", []))
        | {"authorization", "x-keeplane-gateway-credential"}
    )
    result.setdefault("binds", []).append(
        {
            "port": port,
            "listeners": [
                {
                    "name": "keeplane-runtime",
                    "protocol": "HTTP",
                    # Gateway transformations precede route entry auth. Route header
                    # modifiers run afterward and cannot establish this boundary in time.
                    "policies": {
                        "transformations": {"request": {"set": {MARKER: '"1"'}}}
                    },
                    "routes": [
                        {
                            "name": "keeplane-chat",
                            "matches": [
                                {
                                    "method": "POST",
                                    "path": {"exact": "/v1/chat/completions"},
                                }
                            ],
                            "backends": [{"backend": "llm:router"}],
                            "policies": {
                                "extAuthz": callback(
                                    callback_host,
                                    "/internal/runtime/installed/entry",
                                    "json(request.body).model",
                                ),
                            },
                        }
                    ],
                }
            ],
        }
    )
    policies = result.setdefault("policies", [])
    for model_id, declaration in models.items():
        target = {"backend": {"backend": {"name": targets[model_id], "namespace": ""}}}
        suffix = hashlib.sha256(model_id.encode()).hexdigest()[:32]
        selected = selected_callback(
            callback_host, model_id, declaration["fingerprint"]
        )
        policies.append(
            {
                "name": {"name": "keeplane-auth-" + suffix, "namespace": ""},
                "target": target,
                "policy": {
                    "extAuthz": selected,
                },
            }
        )
        if declaration["key_choice"] == "personal":
            policies.append(
                {
                    "name": {"name": "keeplane-key-" + suffix, "namespace": ""},
                    "target": deepcopy(target),
                    "policy": {
                        "backendAuth": {
                            "oauthTokenExchange": personal_exchange(
                                callback_host, model_id, declaration["fingerprint"]
                            )
                        }
                    },
                }
            )
        # Backend transformations run after successful final auth and native
        # provider-key injection. Never carry caller headers to the provider.
        outbound = '{"content-type": "application/json"'
        if declaration["key_choice"] in ("shared", "personal"):
            outbound += ', "authorization": request.headers["authorization"]'
        outbound += "}"
        policies.append(
            {
                "name": {"name": "keeplane-strip-" + suffix, "namespace": ""},
                "target": deepcopy(target),
                "policy": {
                    "transformations": {"request": {"replace": outbound}},
                },
            }
        )
    return result
