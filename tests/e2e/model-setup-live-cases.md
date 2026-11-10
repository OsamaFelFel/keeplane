# Model setup on the running guarded gateway

**Edition:** Open Source. Spec 004 ST23 "A model added outside Keeplane" and
ST24 "Listed but unused", "Set it up" and "Set it up with data classes off";
task 004-01, ADR 027. The [live runner](test_model_setup_live.py) proves that
an admin's Set up reaches the Docker preview's managed gateway (the real,
pinned gateway image) through the model enroller, without restarting the
gateway or the app, and that a model Keeplane hasn't set up gets no work.

Run on the Docker preview, with host port 14424 free:

```sh
python3 deploy/local/up.py
.venv/bin/python -m pytest tests/e2e/test_model_setup_live.py -m live
```

The suite skips, with the reason, when the preview, its credentials, Docker,
the model enroller or that port are not available. It takes about 8 minutes:
a changed or removed model holds the enroller for about 3 minutes and 16
seconds each time (ADR 027).

## Fixtures

- A runner on the host at the preview's allowed address
  `http://host.docker.internal:14424` that serves two upstream models, "first"
  and "second", and counts every request each receives.
- A temporary developer, signed in, and one project with no data class,
  registered by the developer.
- Data classes off. If they were on, the suite turns them off and back on
  afterwards; turning them off keeps every approval (Spec 005 ST18).
- The models already set up stay as they are. The suite counts them first and
  waits until the enroller reports that many enrolled.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| MSL-LIVE-01 | Put a model pointing at "first" straight into the gateway, outside Keeplane, then send it a signed-in request through the guarded port. | The model is listed in Models and routing as not set up. The enroller still reports only the models set up before, and the request gets no answer: nothing reaches the runner. |
| MSL-LIVE-02 | The admin sets the model up with no key and no data classes, then the developer sends it a request. | Set up succeeds and the model is set up with no classes. Within 90 seconds the enroller reports one more model enrolled. The request returns 200 with the runner's answer and reaches "first" once. The gateway container has not restarted. |
| MSL-LIVE-03 | Change the model's destination in the gateway to "second", outside Keeplane, and send a request at once and again after the enroller settles. | The model shows as not set up again. Both requests get no answer and reach neither upstream. The enroller says a model change is waiting, then reports only the models set up before. |
| MSL-LIVE-04 | The admin sets the model up again, then the developer sends a request. | Set up succeeds and the enroller reports one more model enrolled. The request returns the runner's answer and reaches "second" once and "first" never. The gateway container has not restarted. |
| MSL-LIVE-05 | The admin removes the model's setup; the developer sends a request at once and again after the enroller settles. | Removal says the gateway model was kept, and the model is still listed as not set up. Both requests get no answer and reach nothing. The enroller settles on the models set up before. The gateway container has not restarted. |

## Restoring the preview

Afterwards the suite removes the model's setup if it is still there, removes
the model from the gateway, removes the developer, turns data classes back on
if they were on, and waits until the enroller reports the starting number of
models again. A restore step that can't be confirmed fails the run.

## Not covered here

- A customer-run gateway: Keeplane has no enroller there, and the operator
  configures the gateway's protected checks by hand
  ([customer-run gateway cases](existing-gateway-cases.md)).
- Kubernetes gateway copies: the chart's enroller, guard-status table and
  per-copy check are covered by the
  [chart enroller cases](../integration/chart-model-enroller-cases.md) and the
  [guard-status cases](../integration/guard-status-cases.md).
- Models with a shared or developer's own provider key.
