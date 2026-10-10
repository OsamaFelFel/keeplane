# Isolated gateway runtime and management keys

These are local gateway policy checks against the pinned image. Keys are fresh on every run and are never written into evidence. Run `python3 tests/e2e/gateway-policy/verify_strict_keys.py <new JSON path>` while the Docker model fixture is running. The script removes its gateway container afterward.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| GW-KEY-01 | From a sibling container with no key, list models, read management, call the model, then repeat the call with an invalid bearer and forged identity headers. | All return 401 or 403; the fixture call count does not increase. |
| GW-KEY-02 | Use only the runtime key to list and call the model, then read management. | Runtime works; management refuses this key. |
| GW-KEY-03 | Use only the admin key to read management, then call the model. | Management works; model traffic refuses this key. |

These checks prove key separation in one isolated container. They do not prove project binding, class policy, alternate model APIs, replica convergence, Kubernetes isolation, or a release-approved image.
