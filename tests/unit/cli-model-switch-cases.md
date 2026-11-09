# See which model answered, and switch with `keeplane use`

Spec 004 ST17 "See the model", "Switch the model" and "My switch beats Keeplane's
picks" (D105, D150, ADR 030); the CLI side of ST12, ST14 and ST16. Journey:
DEV-02, DEV-03. Synthetic server and runtime doubles in a sample clone; run
`python -m pytest tests/unit/test_cli_model_switch.py`. The real routes are in
the [integration cases](../integration/cli-model-switch-cases.md).

| Case | Expected result |
| --- | --- |
| SW-01 Switch | `keeplane use general` with `general` allowed prints "This repo's next tasks use general. Run `keeplane use --auto` to let Keeplane choose again." It saves `general` under the repo's project ID in the private (0600) settings file, and asks only the account and the allowed list. Another project has no switch. |
| SW-02 Not allowed | `keeplane use outside` for a model the project doesn't allow exits 1 with "outside isn't allowed for this project, so nothing was saved. Choose one that `keeplane models` lists." No settings file is written. |
| SW-03 Code uses the switch | `keeplane code "task"` sends the switch as the `task-model` route's `model_id`, runs that model, says "Using general for this task, as you chose with `keeplane use`. Run `keeplane use --auto` to let Keeplane choose." and, after the turn, "Answered by general." |
| SW-04 Back to Keeplane's pick | `keeplane use --auto` clears the switch without a sign-in or any request, and says "This repo's next tasks use the model Keeplane chooses." `code` then asks the route with no model and says "Using coder for this task, chosen by Keeplane. Run `keeplane use MODEL` to choose another." |
| SW-05 The list marks the choice | `keeplane models` marks the current model (`"current": true`) and says who chose it (`"chosen_by"`: `keeplane` or `you`). A switch the project no longer allows marks none and says so on stderr. If Keeplane's pick can't be asked (404, 503), the list still shows, unmarked. |
| SW-06 Switch no longer allowed | `code` with such a switch sends nothing and says "You switched this repo to retired, but it isn't allowed for this project now, so nothing was sent. Run `keeplane use MODEL` with a model `keeplane models` lists, or `keeplane use --auto` to let Keeplane choose." The server's own 403 for the switch gives the same message. |
| SW-07 Own key unusable | When the server moves the switched task because the developer's own key is missing or refused, `code` says why and how to fix the key, runs the server's model, and ends "Answered by coder." The switch is kept. With no other model, nothing is sent. |
| SW-08 Switch can't be used now | A switched model the gateway can't take right now stops with the existing "… can't be used right now, so nothing was sent" message. |
| SW-09 Older server | With no `task-model` route (404), the switch goes through the model-choice route. |
| SW-10 One turn | `--model coder` is for that turn only: the route isn't asked and the switch stays. |
| SW-11 Answers that don't match | A route answer that drops or replaces the switch, claims a developer switch that wasn't sent, moves a model to itself, names a persona not asked for, or is otherwise inconsistent is refused as an invalid model choice. |
| SW-12 Messages | "Answered by MODEL." only after a finished turn. The ST16 messages name `keeplane use`, not `--model`; the decided #52 and #57 sentences are unchanged. |
| SW-13 Use needs one model or --auto | `use` with neither or both exits 2. Signed out: "You're signed out of Keeplane, so nothing was saved. Run `keeplane login` to sign in." Expired: "Your Keeplane sign-in has expired. Nothing was saved. Run `keeplane login` to sign in again." |
