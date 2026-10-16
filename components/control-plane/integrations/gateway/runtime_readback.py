"""Strict applied native readback for the opt-in managed installation."""

from copy import deepcopy
from urllib.parse import urlsplit

from .runtime_config import MARKER, RuntimeInstallationUnavailable, model_backends


def compiled_callback(config):
    """Expected pinned-native serialization; secrets stay redacted in readback."""
    result = deepcopy(config)
    result["inlineBackend"] = result.pop("host")
    auth = result["policies"]["backendAuth"]
    auth["key"]["value"] = "<redacted>"
    result["policies"] = [{"backendAuth": auth}]
    result["protocol"]["http"]["redirect"] = None
    return result


def compiled_exchange(config):
    if (
        config.get("cache") != {"maxEntries": 0}
        or type(config["cache"]["maxEntries"]) is not int
    ):
        raise RuntimeInstallationUnavailable("Personal key caching is unsupported")
    result = deepcopy(config)
    # The pinned native serializer omits cache entirely. Its configured zero
    # limit is bound by the complete file/effective digests, not this snapshot.
    del result["cache"]
    result["inlineBackend"] = result.pop("host")
    auth = result["policies"]["backendAuth"]
    auth["key"]["value"] = "<redacted>"
    result["policies"] = [{"backendAuth": auth}]
    bearer = {"header": {"name": "authorization", "prefix": "Bearer "}}
    location = result.get("authorizationLocation", bearer)
    if location not in (bearer, {"header": {"name": "x-api-key", "prefix": ""}}):
        raise RuntimeInstallationUnavailable("The Personal key location is unsupported")
    result.update(
        grantType="tokenExchange",
        subjectToken={
            "source": bearer,
            "tokenType": "urn:ietf:params:oauth:token-type:access_token",
        },
        authorizationLocation=deepcopy(location),
    )
    return result


def require_applied_overlay(dump, generated, models, targets):
    """Prove exact serving entry/final guards before creating an active manifest."""

    def same(actual, expected):
        if actual != expected:
            raise RuntimeInstallationUnavailable("The native guard is not applied")

    same(model_backends(dump, models), targets)
    policies = {row["key"]: row for row in dump["policies"]}
    same(len(policies), len(dump["policies"]))
    expected_keys = set()
    for config in generated["policies"]:
        name = config["name"]["name"]
        key = "/" + name
        expected_keys.add(key)
        selected = "extAuthz" in config["policy"]
        if selected:
            policy = {"extAuthz": compiled_callback(config["policy"]["extAuthz"])}
        elif "backendAuth" in config["policy"]:
            policy = {
                "backendAuth": {
                    "oauthTokenExchange": compiled_exchange(
                        config["policy"]["backendAuth"]["oauthTokenExchange"]
                    )
                }
            }
        else:
            policy = {
                "transformation": {
                    "request": config["policy"]["transformations"]["request"],
                    "response": None,
                }
            }
        same(
            policies.get(key),
            {
                "key": key,
                "name": {"kind": "Local", "name": name, "namespace": ""},
                "target": config["target"],
                "policy": {"backend": policy},
            },
        )
    for listener, value, key in (
        ("default", '"operator"', "gateway/default/0"),
        (
            "keeplane-runtime",
            '"1"',
            "listener/default/default/bind/5000/keeplane-runtime/0",
        ),
    ):
        expected_keys.add(key)
        same(
            policies.get(key),
            {
                "key": key,
                "name": None,
                "target": {
                    "gateway": {
                        "gatewayName": "default",
                        "gatewayNamespace": "default",
                        "listenerName": listener,
                    }
                },
                "policy": {
                    "traffic": {
                        "phase": "gateway",
                        "transformation": {
                            "request": {"set": [[MARKER, value]]},
                            "response": None,
                        },
                    }
                },
            },
        )
    same(set(policies), expected_keys)
    binds = [row for row in dump["binds"] if row["key"] == "bind/5000"]
    if len(binds) != 1:
        raise RuntimeInstallationUnavailable("The protected listener is unavailable")
    bind = binds[0]
    if bind["address"] not in ("[::]:5000", "0.0.0.0:5000"):
        raise RuntimeInstallationUnavailable("The protected listener is unsupported")
    listener_key = "default/default/bind/5000/keeplane-runtime"
    route_key = listener_key + "/default/keeplane-chat"
    route = generated["binds"][-1]["listeners"][0]["routes"][0]
    same(
        bind,
        {
            "key": "bind/5000",
            "address": bind["address"],
            "protocol": "http",
            "tunnelProtocol": "direct",
            "mode": "standard",
            "listeners": {
                listener_key: {
                    "key": listener_key,
                    "gatewayName": "default",
                    "gatewayNamespace": "default",
                    "listenerName": "keeplane-runtime",
                    "hostname": "",
                    "protocol": "HTTP",
                    "routes": {
                        route_key: {
                            "key": route_key,
                            "name": "keeplane-chat",
                            "namespace": "default",
                            "matches": route["matches"],
                            "backends": [{"weight": 1, "backend": "/llm:router"}],
                            "inlinePolicies": [
                                {
                                    "extAuthz": compiled_callback(
                                        route["policies"]["extAuthz"]
                                    )
                                }
                            ],
                        }
                    },
                }
            },
        },
    )

    raw = next(row for row in dump["binds"] if row["key"] == "bind/4000")
    routes = raw["listeners"]["gateway/default"]["routes"]
    private = [
        row for row in routes.values() if row["name"] == "keeplane-applied-state"
    ]
    if len(private) != 1:
        raise RuntimeInstallationUnavailable(
            "The private applied-state route is unavailable"
        )
    private = private[0]
    native_key_policy = {
        "aPIKey": {
            "users": "<redacted>",
            "mode": "strict",
            "location": {
                "header": {"name": "authorization", "prefix": "Bearer "},
            },
        }
    }
    same(
        private["matches"],
        [{"path": {"exact": "/internal/keeplane/applied"}, "method": "GET"}],
    )
    same(
        private["inlinePolicies"],
        [
            {"urlRewrite": {"path": {"full": "/config_dump"}}},
            native_key_policy,
            {"budget": {}},
        ],
    )
    ref = "/gateway/default/default/keeplane-applied-state/backend0"
    same(private["backends"], [{"weight": 1, "backend": ref}])
    private_backends = [
        row
        for row in dump["backends"]
        if row.get("backend", {}).get("host", {}).get("name") == ref[1:]
    ]
    same(
        private_backends,
        [
            {
                "backend": {
                    "host": {
                        "name": ref[1:],
                        "namespace": "",
                        "target": "127.0.0.1:15000",
                    }
                }
            }
        ],
    )
    llm = next(row for row in routes.values() if row["name"] == "llm:request")
    same(llm["backends"], [{"weight": 1, "backend": "/llm:router"}])
    same(llm["inlinePolicies"], [native_key_policy, {"budget": {}}])


def require_applied_models(dump, resources, models, targets):
    """Match concrete native endpoints to the complete approved raw definitions."""
    for model_id, target in targets.items():
        value = next(row["value"] for row in resources if row["id"] == model_id)
        rows = [
            row
            for row in dump["backends"]
            if row.get("backend", {}).get("ai", {}).get("name") == target
        ]
        if len(rows) != 1:
            raise RuntimeInstallationUnavailable("The applied provider is unavailable")
        row = rows[0]
        provider = value["provider"]
        provider = (
            {provider: {"model": value["params"]["model"]}}
            if isinstance(provider, str)
            else {
                "custom": {
                    "model": value["params"]["model"],
                    "formats": [{"type": "completions", "path": None}],
                }
            }
        )
        host, prefix = None, None
        if "baseUrl" in value["params"]:
            url = urlsplit(value["params"]["baseUrl"])
            host = url.hostname
            if ":" in host:
                host = "[" + host + "]"
            host += ":" + str(
                url.port
                if url.port is not None
                else (443 if url.scheme == "https" else 80)
            )
            prefix = url.path.rstrip("/") or "/"
        groups = row["backend"]["ai"]["target"]["providers"]
        if (
            len(groups) != 1
            or set(groups[0]) != {"active", "rejected"}
            or set(groups[0]["active"]) != {model_id}
            or groups[0]["rejected"]
        ):
            raise RuntimeInstallationUnavailable(
                "The applied provider group is unsupported"
            )
        expected = {
            "name": model_id,
            "provider": provider,
            "hostOverride": host,
            "pathOverride": None,
            "pathPrefix": prefix,
            "tokenize": False,
        }
        if (
            groups[0]["active"][model_id]["endpoint"] != expected
            or groups[0]["active"][model_id]["capacity"] != 1
        ):
            raise RuntimeInstallationUnavailable(
                "The applied provider definition changed"
            )
        expected_policies = []
        if (
            "baseUrl" in value["params"]
            and urlsplit(value["params"]["baseUrl"]).scheme == "https"
        ):
            expected_policies.append({"backendTLS": {"systemRoots": True}})
        if models[model_id]["key_choice"] == "shared":
            expected_policies.append({"backendAuth": {"key": {"value": "<redacted>"}}})
        expected_policies.append({"ai": {}})
        if row.get("inlinePolicies", []) != expected_policies:
            raise RuntimeInstallationUnavailable(
                "The applied provider authentication changed"
            )
