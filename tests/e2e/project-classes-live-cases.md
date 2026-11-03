# Project classes through the guarded preview gateway

Spec 005 ST19, task 005-02. These cases run real requests through the Docker
preview's managed gateway, on the guarded endpoint that
`deploy/local/up.py --runtime-model` installs. The isolated checks are in the
[project cases](../integration/project-cases.md) and
[model-choice cases](../integration/model-choice-cases.md); the screen is
covered by the [Projects browser cases](../browser/projects-cases.md).

Run after `python3 deploy/local/up.py`, with no guarded endpoint already
enrolled and host port 14424 free:

```sh
.venv/bin/python -m pytest tests/e2e/test_project_classes_live.py -m live
```

The suite skips, with the reason, when the preview, its credentials, Docker or
those ports are not available. It is part of the `docker` regression group.

## Fixtures

- A runner on the host at the preview's allowed address
  `http://host.docker.internal:14424` serves three upstream models and counts
  every request it receives for each one.
- Three temporary models from that runner: a Confidential model, a second
  Confidential model and a Public-only model. The first and the Public-only
  model are enrolled on a fresh guarded gateway with `up.py`'s installer. The
  model enroller (ADR 027) then enrols every usable set-up model, the second
  Confidential model too; the cases start once it reports all three.
- One temporary developer and one new project registered by that developer's
  first use.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| PCL-LIVE-01 | The admin sets the project's class to Confidential. | Projects lists the project with Confidential, and reading the class back gives Confidential. |
| PCL-LIVE-02 | The developer sends a task to the Confidential model through the guarded gateway. | The answer comes back, the runner sees one request for that model and none for the Public-only model, and the project's model list leaves out the Public-only model. |
| PCL-LIVE-03 | The developer names the Public-only model directly, again with forged class, account and operator headers, and an admin tries the same model for the project. | The gateway refuses every request with 403, the CLI's model choice is refused with 403, and the runner receives nothing. |
| PCL-LIVE-04 | The repository's own settings name the Public-only model, or the provider's own model name. | The CLI's model list for the project doesn't include it and its model choice is refused. The gateway refuses both names, and the runner receives nothing. |
| PCL-LIVE-05 | The admin sets the class to None, then the developer uses both models. | The project's model list includes every set-up model, the CLI keeps the Public-only model, and both models answer through the gateway. |
| PCL-LIVE-06 | The class is Confidential again and the Confidential model's provider is down. The developer uses it, then names the Public-only model. | The CLI keeps the Confidential model: Keeplane doesn't move the task. The gateway tries that model three times (the first attempt and two retries), then returns an error. The other Confidential model, which is up, and the Public-only model receive nothing, and the Public-only model is refused with 403. |

## Restoring the preview

Afterwards the suite removes the model enroller and recreates the gateway and
app from `compose.yaml` alone,
so the guarded endpoint is gone and the ordinary gateway configuration is back.
It removes the guarded installation volume if the run created it. It clears
the project's class, removes the three models from Keeplane and the gateway,
removes the developer, and restores the data-class mode. Keeplane has no way to
remove a project, so the project record stays with no class. A restore step
that can't be confirmed fails the run.

PCL-LIVE-06 used to need a Confidential model that was set up but not enrolled,
so the CLI would say "… is approved for this project but can't be used right
now, so nothing was sent." The model enroller (ADR 027) now enrols every usable
set-up model within seconds, so the live preview no longer has that state. The
case now makes the model unusable by taking its provider down (Spec 004 ST16;
issue #37, no automatic switch). The "set up but not enrolled" refusal and its
CLI wording stay covered by the integration tests in the
[project cases](../integration/project-cases.md) and
[model-choice cases](../integration/model-choice-cases.md).

The provider failure in PCL-LIVE-06 is shown at the gateway. A real coding run
reports it through the coding runtime, which this suite doesn't start.
