# Release journey installs

**Edition:** Open Source. Task 009-15. These checks read what the disposable
installs of the [release journey cases](../e2e/developer-journey-release-cases.md)
would start (`tests/fixtures/release_journey.py`), with no Docker, so a change
that breaks one of the guides' rules fails before the live run. Run with
`.venv/bin/python -m pytest tests/unit/test_release_journey_installs.py`.

| ID | Plain-English check | Expected result |
| --- | --- | --- |
| RJI-01 | Read the customer-run gateway's file for one local and one cloud model. | As the [gateway guide](../../docs/guide/gateway-configuration.md#keeplanes-checks-on-a-customer-run-gateway) says: the developer listener sets the marker with `set`, before routing; the developer route has the route check, refusing when Keeplane can't answer, with the gateway credential and the retry. Each model, the customer's own one included, has the final check first, which sends marked requests to the final check and unmarked ones to the key-only check, and a last step that passes on only the provider's headers: `authorization` only for the cloud model, whose backend alone adds the customer's provider key. |
| RJI-02 | Read both installs' Compose files. | Only the one address in front of the app copies and the gateway's developer listener have ports, both on loopback; the gateway's management address has none. The app copies give CLIs the developer listener's address, in the install's mode. |
| RJI-03 | Read both installs' app copies. | The two copies have the same settings: one PostgreSQL database and one signing secret. Both run read-only with no extra capabilities, and the address in front sends to both. |
| RJI-04 | Read the managed install's enroller, and the existing install's gateway. | The enroller runs in the gateway's network with no port, as its own database role, read-only; the managed gateway reads the installer's file. The existing install has no enroller, and its gateway reads the customer's file. |
| RJI-05 | Send four requests through the one address to two copies. | They go to the copies in turn. Each copy gets the browser's own `Host` and the body unchanged, every cookie comes back, and each copy is counted twice. |
