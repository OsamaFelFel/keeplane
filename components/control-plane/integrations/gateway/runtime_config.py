"""Native configuration for the opt-in, managed local runtime installation."""

import hashlib
import json
import re
from copy import deepcopy

from .applied import private_applied_route

MARKER = "x-keeplane-installed-runtime"
PROTECTED = f'request.headers["{MARKER}"] == "1"'
OPERATOR = f'request.headers["{MARKER}"] == "operator"'
# Spec 005 ST20, only for an install set up for personal-data detection: the
# request's messages go to Keeplane's own check. A body over 1 MiB sends null,
# which the check holds as not inspected, so no size limit can refuse traffic.
MESSAGES_LIMIT = 1024 * 1024
MESSAGES = (
    f'"messages": size(request.body) <= {MESSAGES_LIMIT} '
    "? json(request.body).messages : null"
)
# ADR 027, Kubernetes: each copy's guard names the copy (its StatefulSet Pod
# name) in every protected check, so the app checks that copy's own confirmed
# guard-status row. It is a constant written by the copy's own enroller, never
# a value a client can set.
COPY_NAME = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")
COPY_FIELD = '"gateway_copy": '


def copy_field(gateway_copy):
    """The body text naming the copy; empty when no copy is named."""
    if gateway_copy is None:
        return ""
    if not isinstance(gateway_copy, str) or not COPY_NAME.fullmatch(gateway_copy):
        raise RuntimeInstallationUnavailable("The gateway copy name is not valid")
    return ", " + COPY_FIELD + json.dumps(gateway_copy)


# Spec 004 ST16, owner decision of 31 October 2026: a model that is down gets
# the same request twice more, then the developer is told. Native retries go to
# the same route backend, and every attempt passes the selected-model check
# again. A status is final before any byte of the answer reaches the client, so
# a stream that has started is never retried. Keeplane never switches models here.
RETRY_ATTEMPTS = 2
# Every 5xx, listed explicitly: the native policy takes exact codes, not ranges.
# Connection failures before any request reaches the provider are retried natively.
RETRY_CODES = (429, *range(500, 600))
RETRY_BACKOFF = "500ms"
# Per attempt, up to the provider's response headers; a started stream is not cut.
ATTEMPT_TIMEOUT = "60s"


def outage_retry():
    """The native route policies that retry a model that is down."""
    return {
        "retry": {
            "attempts": RETRY_ATTEMPTS,
            "codes": list(RETRY_CODES),
            "backoff": RETRY_BACKOFF,
        },
        "timeout": {"backendRequestTimeout": ATTEMPT_TIMEOUT},
    }


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


def callback(
    host,
    path,
    model_expression,
    fingerprint=None,
    *,
    messages=False,
    gateway_copy=None,
):
    fields = (
        '{"project_id": request.headers["x-keeplane-project-id"], "model_id": '
        + model_expression
    )
    if fingerprint is not None:
        fields += ', "definition_fingerprint": ' + json.dumps(fingerprint)
    fields += copy_field(gateway_copy)
    if messages:
        fields += ", " + MESSAGES
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


def selected_callback(
    host, model_id, fingerprint, *, messages=False, gateway_copy=None
):
    result = callback(
        host,
        "/internal/runtime/installed/selected",
        json.dumps(model_id),
        fingerprint,
        messages=messages,
        gateway_copy=gateway_copy,
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


def personal_exchange(host, model_id, fingerprint, provider, *, gateway_copy=None):
    if provider not in ("openAI", "anthropic"):
        raise RuntimeInstallationUnavailable("The Personal provider is unsupported")
    params = {
        "project_id": 'request.headers["x-keeplane-project-id"]',
        "model_id": json.dumps(model_id),
        "definition_fingerprint": json.dumps(fingerprint),
    }
    if copy_field(gateway_copy):
        params["gateway_copy"] = json.dumps(gateway_copy)
    result = {
        "host": host,
        "path": "/internal/runtime/installed-provider-token",
        "cache": {"maxEntries": 0},
        "additionalParams": params,
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
    if provider == "anthropic":
        result["authorizationLocation"] = {
            "header": {"name": "x-api-key", "prefix": ""}
        }
    return result


def overlay(
    base,
    models,
    targets,
    *,
    callback_host="app:3000",
    port=5000,
    personal_providers=None,
    send_messages=False,
    gateway_copy=None,
):
    copy_field(gateway_copy)  # refuse a bad copy name before building anything
    if not isinstance(base, dict) or set(models) != set(targets) or not models:
        raise RuntimeInstallationUnavailable(
            "Declare exact installed models and targets"
        )
    personal = {
        model_id for model_id, row in models.items() if row["key_choice"] == "personal"
    }
    personal_providers = {} if personal_providers is None else personal_providers
    if (
        not isinstance(personal_providers, dict)
        or set(personal_providers) != personal
        or any(
            value not in ("openAI", "anthropic")
            for value in personal_providers.values()
        )
    ):
        raise RuntimeInstallationUnavailable(
            "Declare exact validated Personal providers"
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
        | ({"x-api-key"} if "anthropic" in personal_providers.values() else set())
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
                                    messages=send_messages,
                                    gateway_copy=gateway_copy,
                                ),
                                **outage_retry(),
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
            callback_host,
            model_id,
            declaration["fingerprint"],
            messages=send_messages,
            gateway_copy=gateway_copy,
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
                                callback_host,
                                model_id,
                                declaration["fingerprint"],
                                personal_providers[model_id],
                                gateway_copy=gateway_copy,
                            )
                        }
                    },
                }
            )
        # Backend transformations run after successful final auth and native
        # provider-key injection. Never carry caller headers to the provider.
        outbound = '{"content-type": "application/json"'
        if declaration["key_choice"] in ("shared", "personal"):
            header = (
                "x-api-key"
                if personal_providers.get(model_id) == "anthropic"
                else "authorization"
            )
            outbound += f', "{header}": request.headers["{header}"]'
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


def _named_copy(body):
    found = set(re.findall(re.escape(COPY_FIELD) + r'("[a-z0-9-]*")', body))
    if len(found) > 1:
        raise ValueError()
    return json.loads(found.pop()) if found else None


def callback_copies(config):
    """The copy names the protected checks in `config` send.

    None stands for a check that names no copy. The enroller keeps a guard
    only when every check names exactly its own copy (none in the Docker
    preview). Returns None when the configuration cannot be read.
    """
    names = set()
    try:
        for bind in config.get("binds", []):
            for listener in bind.get("listeners", []):
                for route in listener.get("routes", []):
                    auth = route.get("policies", {}).get("extAuthz")
                    if auth is not None:
                        names.add(_named_copy(auth["protocol"]["http"]["body"]))
        for row in config.get("policies", []):
            policy = row["policy"]
            if "extAuthz" in policy:
                names.add(_named_copy(policy["extAuthz"]["protocol"]["http"]["body"]))
            exchange = policy.get("backendAuth", {}).get("oauthTokenExchange")
            if exchange is not None:
                value = exchange["additionalParams"].get("gateway_copy")
                names.add(None if value is None else json.loads(value))
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return names
