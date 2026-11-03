# Personal-data detection through the guarded preview gateway

**Edition:** Open Source. Spec 005 ST20 and Spec 006 ST21 "Held-back
requests", tasks 005-03 and 006-02. These cases send real requests through the
Docker preview's managed gateway, on the guarded endpoint, with personal-data
detection installed: the app runs from the `detection` image target and the
app, the runtime installer and the model enroller all have
`KEEPLANE_PERSONAL_DATA_DETECTION=1`, so every gateway check carries the
request's messages to Keeplane's real detector. The isolated checks are in the
[detection routing cases](../integration/personal-data-routing-cases.md) and
the [held-back request cases](../integration/held-request-record-cases.md);
the detector's quality on the fixed English sets is in the
[detector cases](../integration/personal-data-model-cases.md).

Run after `python3 deploy/local/up.py` and building the detection image, with
no guarded endpoint already enrolled and host port 14424 free:

```sh
docker build -f components/control-plane/Dockerfile --target detection \
  -t keeplane-preview:detection-local .
.venv/bin/python -m pytest tests/e2e/test_personal_data_live.py -m live
```

`KEEPLANE_PREVIEW_DETECTION_IMAGE` names another detection image. The suite
skips, with the reason, when the preview, its credentials, Docker, the
detection image or those ports are not available. CI's **Live preview gateway
checks** workflow runs it in its own job and fails if it is skipped or doesn't
run.

## Fixtures

- The host runner from the [project classes cases](project-classes-live-cases.md)
  at `http://host.docker.internal:14424`, which counts every request each
  upstream model receives.
- Four temporary models from that runner: Public-only, Confidential-only,
  Internal-only, and one approved for both Internal and Confidential. All four
  are enrolled on a fresh guarded gateway with the preview's installer; the
  cases start once the model enroller reports all four.
- One temporary developer and two new projects: one with no class and one
  whose class is Internal.
- Requests from the fixed English set
  (`tests/fixtures/personal_data/english-set.json`): EN2-027 (an email),
  EN2-045 (a phone number) and EN2-061 (a card number), and the clean
  code-shaped requests EN2-146 (code), EN2-151 (a stack trace) and EN2-155 (a
  log line). On that set the detector misses no email, phone or card request
  and holds none of these clean forms (PM-03, PM-04). A long request repeats
  EN2-146 to over 100 000 characters.
- Detection handles requests as Confidential, and the Audit **Held-back
  requests** switch is on except in PDL-LIVE-07.

In every case "the decided message" is: "This request is handled as
Confidential and <model> isn't approved for it, so nothing was sent. Run it
with a model approved for Confidential, or ask your admin to approve one."
A held-back record reads "Request HR-… held back as Confidential (<reason>);
project <project>; approved model <model>" or "…; model <model> isn't approved
for it, nothing was sent", names the developer and a time, has its own
reference and never contains the request text or the email, phone or card
number in it.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| PDL-LIVE-01 | Detection off: the developer sends the three personal-data and three clean requests to the Public-only model from the project with no class. | All six are answered and reach the Public-only model; no held-back record is written. |
| PDL-LIVE-02 | The admin turns detection on, handling requests as Confidential. The developer sends each personal-data request to the Public-only model, then to the Confidential model. | Data classes show detection on, Confidential, installed. Each Public-only request is refused with 403 and the decided message, and nothing reaches that model. Each Confidential request is answered. Six records: three "model … isn't approved for it, nothing was sent" for the Public-only model and three "approved model …" for the Confidential model, each with "Personal data detected" and the project's name. |
| PDL-LIVE-03 | With detection on, the developer sends the three clean requests to the Public-only model. | All three are answered and reach the Public-only model; no record. |
| PDL-LIVE-04 | From the Internal project, the developer sends the email request to the Confidential-only, Internal-only and Internal-and-Confidential models, then a clean request to the Internal-only and Confidential-only models. | The personal-data request goes only to the model approved for both classes; the other two are refused with the decided message and receive nothing. The clean request reaches the Internal-only model; the Confidential-only model is refused by the project's own class, without the detection message. Three records, two refused and one approved, with the Internal project's name. |
| PDL-LIVE-05 | The developer sends the long request to the Public-only model, then to the Confidential model. | Held without a check: the Public-only model is refused with the decided message and receives nothing; the Confidential model answers. One record each, "Detection took longer than 200 ms": the final model check doesn't record the same request again. |
| PDL-LIVE-06 | The app is restarted with the detector unable to load its model while detection stays on. The developer sends a clean request to the Public-only model, then to the Confidential model. Then the app is restarted with its detector again. | Data classes show detection on but not installed. The clean request is held: refused for the Public-only model with the decided message, answered by the Confidential model. Records say "Detection was down": one for the refused request, and for the answered one a record from the entry check plus one per final model attempt (a duplicate during an outage, accepted in keeplane #204). After the restart detection is installed again. |
| PDL-LIVE-07 | The admin turns the Held-back requests switch off; the developer sends the phone request to the Public-only and Confidential models. | Still held: refused for the Public-only model with the decided message, answered by the Confidential model. No record. |
| PDL-LIVE-08 | The admin turns the switch back on and detection off; the developer sends the card request and the long request to the Public-only model. | Both are answered and reach the Public-only model; no record. |

## Restoring the preview

Afterwards the suite puts detection, its class and the Held-back requests
switch back as they were, clears both projects' classes, and then restores the
preview exactly as the project classes suite does: it removes the model
enroller, recreates the gateway and app from `compose.yaml` alone (so the app
runs the ordinary image without detection again), removes the guarded
installation volume if the run created it, removes the four models and the
developer, and restores the data-class mode. Keeplane has no way to remove a
project, so the two project records stay with no class. A restore step that
can't be confirmed fails the run.

## Not covered here

- Names and addresses: the detector misses a few of these on the fixed sets
  (within the release-1 bar), so a live case would depend on which request is
  picked. The detector cases cover every kind on both English sets.
- A detector that is slow or fails while loaded: only the "too long to check"
  and "down" paths can be caused from outside the app. The routing cases
  (PR-04) and detector checks (PD-06) cover slow and failing detectors.
- What the developer's coding runtime shows: these cases read the gateway's
  answer, as the project classes cases do.
