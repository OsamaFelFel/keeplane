# Enroller database mount cases

**Edition:** Open Source. Spec 004 ST10 and ST23, ADR 027.
[`test_enroller_database_mount.py`](test_enroller_database_mount.py) renders
`compose.yaml` with `deploy/local/runtime.yaml` (`docker compose config`, which
starts nothing) and runs `deploy/local/prepare_volumes.py` on temporary folders.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| EDM-01 | Render the guarded preview and look at the model enroller's mounts. | Of the account volume it mounts only the `database` folder, read-only, at `/state/database`; nothing else under `/state`. Its database connection is read-only and opens the file in that folder. |
| EDM-02 | Look at every service that opens the app database. | The app, its migration step, the runtime installer and the enroller all open `/state/database/keeplane.sqlite3`; the writers keep the whole account volume. No service names a PostgreSQL server: the Docker preview has no PostgreSQL mode, so no enroller database mount applies there. |
| EDM-03 | Load the app's settings and the enroller command with the enroller's environment and no signing secret. | The database opens with `mode=ro`, Django's start-up checks pass and the signing secret stays empty: the enroller doesn't need it. |
| EDM-04 | Prepare a new preview's volumes, twice. | The `database` folder exists, mode 0700, and stays empty until the app migrates. |
| EDM-05 | Prepare volumes that hold a database at the earlier path, then start again. | The first start gives the same file a second name in the folder, so an app still running from before keeps writing the database the new one reads; the next start removes the earlier name. An empty file created at the earlier path afterwards is removed. The approvals are unchanged throughout. |
| EDM-06 | Prepare volumes whose earlier database has a journal beside it, or where both paths hold different databases. | Start-up stops with a message and changes neither file. |

Not proven here: the mounts inside running containers. The guarded preview's
live run (`tests/integration/test_managed_runtime_orchestration.py`) checks the
same mounts in its own Compose project and runs them; it needs the gateway
image.
