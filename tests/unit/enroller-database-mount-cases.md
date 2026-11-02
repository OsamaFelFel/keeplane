# Enroller database mount cases

**Edition:** Open Source. Spec 004 ST10 and ST23, ADR 027.
[`test_enroller_database_mount.py`](test_enroller_database_mount.py) renders
`compose.yaml` with `deploy/local/runtime.yaml` (`docker compose config`, which
starts nothing) and runs `deploy/local/prepare_volumes.py` on temporary folders and the
launcher's notice step with Docker substituted.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| EDM-01 | Render the guarded preview and look at the model enroller's mounts. | Of the account volume it mounts only the `database` folder, read-only, at `/state/database`; nothing else under `/state`. Its database connection is read-only and opens the file in that folder. |
| EDM-02 | Look at every service that opens the app database. | The app, its migration step, the runtime installer and the enroller all open `/state/database/keeplane.sqlite3`; the writers keep the whole account volume. No service names a PostgreSQL server: the Docker preview has no PostgreSQL mode, so no enroller database mount applies there. |
| EDM-03 | Load the app's settings and the enroller command with the enroller's environment and no signing secret. | The database opens with `mode=ro`, Django's start-up checks pass and the signing secret stays empty: the enroller doesn't need it. |
| EDM-04 | Prepare a new preview's volumes, twice. | The `database` folder exists, mode 0700, and stays empty until the app migrates. |
| EDM-05 | Prepare volumes that still hold an earlier preview's `keeplane.sqlite3`, `accounts.sqlite3` or `model-approvals.sqlite3` (the earlier database alone, the two older files, or all three), twice. | No migration (ADR 014): each earlier file keeps its bytes and modification time, the new folder stays empty for a fresh database, and each start prints a notice naming exactly the files found, saying they aren't used or imported, and giving the full reset (`docker compose -f compose.yaml -f deploy/local/runtime.yaml --profile runtime down --remove-orphans`, which also stops the enroller, then `docker volume rm keeplane-accounts-trial_model-approvals`). The guarded-runtime guide gives the same commands. |
| EDM-06 | The launcher reads the volume step's log after starting. | It asks only for this start's log, repeats each notice line once and prints nothing when there is none. |
| EDM-07 | Run the preview's own migration step (from the rendered `app-migrate` command) on a volume that holds earlier `accounts.sqlite3` and `model-approvals.sqlite3`. | The step doesn't run `import_preview`; the new database has only the first admin and no approved models, and the earlier files are unchanged. |

Not proven here: the mounts inside running containers. The guarded preview's
live run (`tests/integration/test_managed_runtime_orchestration.py`) checks the
same mounts in its own Compose project and runs them; it needs the gateway
image.
