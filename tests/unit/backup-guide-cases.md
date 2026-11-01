# Backup guide commands

These cases keep [Back up and restore](../../docs/guide/backup-and-restore.md)
true to the Docker preview, the chart and the app (tasks 002-02 and 003-03).
They read the guide's shell blocks as text and compare them with `compose.yaml`,
the app image, the chart templates and the app's management commands. No
Docker, Kubernetes or Helm is needed.

Run `.venv/bin/python -m pytest tests/unit/test_backup_guide.py`.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| BG-01 | Read every `docker compose` line in the guide. | Each acts on the right preview service (`app` for exec, copy and restart; `volume-init` for the helper runs; `gateway` for stop, start and logs), and every path inside a container is on a volume that service mounts, or one the line adds with `-v`. Checks run as `python manage.py` in `app`. |
| BG-02 | Count the `manage.py` checks shown for Kubernetes. | `verify_restore` and `check_credentials` appear, each Kubernetes form has a Docker form beside it, Kubernetes runs `/app/manage.py`, and the preview's app runs from `/app`. |
| BG-03 | Look up every `manage.py` command and flag the guide names. | Each is a command this Keeplane version has, and its flags parse. |
| BG-04 | Compare the guide's Docker volume names and owners with `compose.yaml`. | The three volumes have Docker's real names; the gateway runs as its image's user, which owns `/data` because `volume-init` gives it that UID; the guide's `chown` after a gateway restore uses the same UID, and the app's UID matches the image. |
| BG-05 | Compare the guide's `kubectl` lines with the chart. | The app Deployment, its `app` label and container, the gateway StatefulSet, the trial's state and key claims and the `/state` and `/provider-keys` mounts have the names the guide uses. |
| BG-06 | Compare the guide's file paths with the app's defaults. | The app database, signing secret and gateway database paths are the ones the app and the preview's gateway use, and both trials make a signing secret only when none is there. |
| BG-07 | Collect every `python -c` line in the guide. | Each is one the backup and restore cases run, or the signing-secret write, which keeps the existing file's mode 0600 and writes the backup's bytes exactly. |
| BG-08 | Follow every link in the guide. | Each file exists and each `#anchor` is a heading in it. |
| BG-09 | As root, restore a gateway database the guide's way into a folder the gateway's UID owns, before and after the guide's `chown`. | Before the `chown`, the file belongs to root and the gateway's UID can't write it; after, it can. Skipped when not run as root. |

Not proven here: the commands themselves against running containers or a
cluster (the network refuses the pinned images in the development environment),
and the gateway image's own user, which is read from how the preview prepares
its volume rather than from the image.
