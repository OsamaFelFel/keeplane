# Retry a model that is down, then stop

Spec 004 ST16, owner decision of 31 October 2026. The disposable native trial
adds the product's own route policy (`outage_retry()` from the runtime
installer) to the protected route of the
[native authorization fixture](native-runtime-authorization-cases.md). Only the
per-attempt timeout is shortened from 60 seconds to 2 seconds so the timeout case
finishes quickly. The mock provider plays a script of answers. Public is set up,
allowed for the project's class and up, so any switch would be visible.

| Case | Provider answers | Expected result |
| --- | --- | --- |
| OUT-01 | 503 three times | The client gets 503; Private was contacted three times, Public never. |
| OUT-02 | 500, 501, 502, 504, 520, 529 or 599 three times | The same status after three contacts with Private only. |
| OUT-03 | 429 three times | 429 after three contacts with Private only. |
| OUT-04 | 503, 503, then an answer | 200 after three contacts. |
| OUT-05 | 429, then an answer | 200 after two contacts. |
| OUT-06 | 503, then an answer, while streaming | 200 stream after two contacts: no byte had been sent. |
| OUT-07 | No headers within the attempt timeout, three times | 504 after three contacts with Private only. |
| OUT-08 | A context-length refusal (400) | 400 at once, one contact, no retry. |
| OUT-09 | A stream fails after its first event | The client sees the partial, incomplete stream; one contact, nothing sent again. |
| OUT-10 | Private's address refuses connections | A 5xx after three selected-model checks for Private; no provider answers and Public receives nothing. |

Every case runs in managed and existing-gateway modes. The fixture labels each
decision with the gateway policy that asked for it (entry or selected model);
the label is set by the gateway configuration, never by the client. Every
contact had exactly one allowed selected-model check for Private, and the entry
check allowed the request, and no developer session reaches the provider. The
report records statuses, model names and script steps only.

Use the [native fixture prerequisites](native-runtime-authorization-cases.md),
then run:

```sh
python -m pytest tests/integration/test_native_runtime_outage.py -m live -q
```

Whether the pinned gateway retries its own per-attempt timeout (OUT-07) is a
native behaviour this case checks; the owner's rule counts a timeout as down.
The installed runtime's compiled route is checked by the managed installer's
readback, not by this fixture.
