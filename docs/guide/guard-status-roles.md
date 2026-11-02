# Set up the model enroller's database roles

On a Kubernetes install with the managed gateway, a private model enroller runs
beside each gateway copy and keeps that copy's protected checks in step with
the saved models (see [the model enroller](../architecture/runtime-authorization.md#model-enroller)).
The app can't read a copy's private files, so each enroller records what it
confirmed on its copy in the **guard-status table**, one row per copy. The app
then lets a protected model call through a copy only when that copy's row lists
the model.

This page is for whoever sets up Keeplane's PostgreSQL database. You create
two kinds of extra login roles, then run one Keeplane command that limits what
each role can do. The chart settings that mount these credentials into the
enroller containers are separate work; until they ship, nothing on this page is
used by a running install. It applies to PostgreSQL only: the Docker preview
keeps no guard-status table.

## What each role may do

| Role | Used by | May do |
| --- | --- | --- |
| Migration role (exists already) | Migration Job | Owns Keeplane's tables; runs the command below |
| App role (exists already) | App copies | Read the guard-status table, never write it |
| Enroller approvals role (new, one for all copies) | Every enroller | Read model approvals only; every transaction read-only by default |
| Status role (new, one per gateway copy) | That copy's enroller | Read, add and update only its own copy's row of the guard-status table; nothing else |

Each copy is named by its StatefulSet Pod name, such as `keeplane-gateway-0`
(`<release>-gateway-<N>`). A status role's row is bound to it inside the
database, so one copy's enroller can't confirm a model for another copy, even
with a mistaken setting.

## 1. Create the roles

Ask your database operator to run this as a role that can create roles (not as
Keeplane's migration or app role). Use your own role names and a separate
random password for each role, and keep the passwords in your secret store.
Repeat the status role lines once per gateway copy.

```sql
CREATE ROLE keeplane_enroller LOGIN PASSWORD '<password>';
ALTER ROLE keeplane_enroller SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE keeplane TO keeplane_enroller;

CREATE ROLE keeplane_status_0 LOGIN PASSWORD '<password>';
ALTER ROLE keeplane_status_0 SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE keeplane TO keeplane_status_0;

CREATE ROLE keeplane_status_1 LOGIN PASSWORD '<password>';
ALTER ROLE keeplane_status_1 SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE keeplane TO keeplane_status_1;
```

Don't give these roles `SUPERUSER`, `BYPASSRLS` or `CREATEROLE`, and don't make
any of them, or the app role, a member of the migration role or of one another,
even without inheriting its privileges (`NOINHERIT` or `INHERIT FALSE`): a
member can switch to the other role. If you revoked
`USAGE` on the schema from `PUBLIC`, also grant `USAGE` on Keeplane's schema to
each role.

The role creation stays with your operator on purpose: Keeplane's own roles
never get permission to create roles, and the passwords never pass through a
Keeplane command or its logs.

## 2. Limit the roles with Keeplane's command

After `migrate`, run this with the **migration** credential (the same
environment the migration Job uses), naming every gateway copy and its status
role:

```sh
python /app/manage.py configure_guard_status_access \
  --app-role keeplane_app \
  --enroller-role keeplane_enroller \
  --copy keeplane-gateway-0=keeplane_status_0 \
  --copy keeplane-gateway-1=keeplane_status_1
```

It reports, for example: "Guard status access is set for 2 gateway copies: the
app reads, each copy writes only its own row, and the enroller reads only
approvals."

The command:

- removes every grant on the guard-status table except the owner's, then gives
  the app role read access and each status role read, add and update access;
- turns on row-level security, with a policy that lets each status role reach
  only the row of the copy you paired it with;
- removes the enroller and status roles' access to every other Keeplane table
  and sequence, then lets the enroller approvals role read model approvals;
- checks the result and changes nothing if any role could still do more, for
  example through a grant to `PUBLIC` or a role membership.

It refuses, changing nothing, when a role doesn't exist yet, when it isn't run
with the role that owns Keeplane's tables, when a role is a superuser, can
bypass row-level security or can create roles, when the app, enroller or a
status role belongs to the migration role or to another of these roles (with or
without inheriting), or when the enroller or a status role doesn't have
`default_transaction_read_only = on`.

Run it again, with the full list, whenever the number of gateway copies
changes. A role you leave out loses its access to the table. A row left by a
removed copy is ignored: the app only accepts copies in its copy list.

Even before you run the command, the migration turns on row-level security for
the table, so the app's ordinary write grants can't change any row.

The row-level security policies name your roles. When you
[restore a backup](backup-and-restore.md) into a server that lacks those
roles, create them first, or run the command again after the restore. Rows
restored from a backup only say what each copy had confirmed then; the app
still checks every copy's live state, and each enroller rewrites its row on its
next pass.

## 3. Settings for each enroller and the app

The enroller reads approvals as the approvals role and writes its copy's row
over a second connection as that copy's status role. Its status write opens an
explicit `BEGIN READ WRITE` transaction; every other transaction on either
connection stays read-only.

| Setting | Where | Value |
| --- | --- | --- |
| `KEEPLANE_DATABASE_USER`, `KEEPLANE_DATABASE_PASSWORD_FILE` | Enroller | The enroller approvals role and its password file |
| `KEEPLANE_DATABASE_READ_ONLY` | Enroller | `1` |
| `KEEPLANE_GATEWAY_COPY` | Enroller | This copy's Pod name, for example from the Pod's `metadata.name` |
| `KEEPLANE_GUARD_STATUS_DATABASE_USER`, `KEEPLANE_GUARD_STATUS_DATABASE_PASSWORD_FILE` | Enroller | This copy's status role and its password file |
| `KEEPLANE_GUARD_STATUS_CHECK` | App | `1` turns on the per-copy check |

The status connection uses the same host, port, database name and TLS settings
as the approvals connection. The enroller refuses to start when only one of
`KEEPLANE_GATEWAY_COPY` and the status role is set, when the database isn't
PostgreSQL, when the approvals connection isn't read-only, or when both
connections use the same role.

With `KEEPLANE_GUARD_STATUS_CHECK=1`, the app needs `GATEWAY_COPY_URLS` to list
every copy at its Pod address (the chart's managed mode already does). A
protected check that names no copy, a copy not in the list, or a copy with no
confirmed row is refused.

## 4. Check the roles

`check_credentials` checks the status roles each time you run it in an app pod
with `KEEPLANE_GUARD_STATUS_CHECK=1` (see
[before and after every rotation](postgres-accounts.md#before-and-after-every-rotation)
for how to run it in a pod). It runs as the app role, changes nothing, and
uses the same checks as `configure_guard_status_access`. It never reads or
prints a status role's password. With SQLite, or with the per-copy check off,
it reports `"guard_status": "not in use"` and doesn't affect `"passed"`.

For each copy in `GATEWAY_COPY_URLS` it shows the status role the
row-level security policy pairs with it, that role's state and what the copy's
row says:

```json
"guard_status": {
  "app_role": "reads only",
  "policies": "as set",
  "row_security": "on",
  "copies": [
    {
      "copy": "keeplane-gateway-0",
      "status_role": "keeplane_status_0",
      "role_status": "limited",
      "guard": "confirmed",
      "confirmed_at": "2026-11-02T08:15:04Z",
      "age_minutes": 95,
      "models": [{"fingerprint": "3f9a…", "id": "team-chat"}],
      "updated_at": "2026-11-02T08:15:04Z"
    },
    {
      "copy": "keeplane-gateway-1",
      "status_role": "keeplane_status_1",
      "role_status": "limited",
      "guard": "not confirmed",
      "updated_at": "2026-11-02T09:48:30Z"
    }
  ]
},
"guard_status_problems": [],
"guard_status_warnings": [
  "Gateway copy keeplane-gateway-1: no guard is confirmed; protected models are refused through it until its enroller confirms one"
]
```

| `"role_status"` | Meaning |
| --- | --- |
| `limited` | The role exists, can log in and can reach only its own copy's row, as the command set it. |
| `cannot log in` | The role is `NOLOGIN`, its password has passed its `VALID UNTIL` date, or it has no `CONNECT` on the database. |
| `unsafe` | The role could do more than the command allows: it is the table owner, a superuser, can bypass row-level security or create roles, belongs to the migration role or another listed role, isn't read-only by default, or holds a privilege beyond reading, adding and updating the guard-status table. |
| `cannot write` | The role lacks reading, adding or updating the guard-status table, so its enroller can't record its row. Run the command again. |
| `missing` | The policy names a role that doesn't exist. |
| `not paired` | No status role is paired with this copy. Run the command again with every copy. |

| `"guard"` | Meaning |
| --- | --- |
| `confirmed` | The copy's enroller confirmed a guard. `confirmed_at` and `age_minutes` say when, and `models` lists each model it confirmed with its definition fingerprint. A confirmation has no time limit: it stays valid until it no longer matches the copy. |
| `not confirmed` | Nothing is confirmed on the copy right now, for example while its checks are swapped or when no protected model is saved. This only warns. |
| `not recorded` | The copy's enroller has never written its row. |
| `unreadable` | The row says confirmed but its guard can't be read; the app refuses that copy. |

`"app_role"` is `reads only`, or `unsafe` when the app role could write the
table. `"row_security"` is `on` or `off`, and `"policies"` is `as set`, or
`changed` when the table's policies aren't the ones the command writes.

The check exits 1, with one sentence per fault under `guard_status_problems`,
when a copy's role is `cannot log in`, `unsafe`, `cannot write`, `missing` or
`not paired`, when a copy's guard is `not recorded` or `unreadable`, when the
app role is `unsafe`, when row-level security is off or the policies changed,
when a status role is still paired with a copy that's no longer in
`GATEWAY_COPY_URLS`, or when the table or the roles can't be read. For example:

```text
Gateway copy keeplane-gateway-0: its status role keeplane_status_0 is a superuser, can bypass row-level security or can create roles
Gateway copy keeplane-gateway-2 is no longer listed but status role keeplane_status_2 is still paired with it; remove the role or its pairing
```

To remove a pairing, run the command again with only the current copies. Only
`not confirmed` copies are listed under `guard_status_warnings`; they don't
fail the check. The check can't tell whether the password mounted for an
enroller is right, because the app never sees it: the enroller's log shows that
(below).

## Rotate a status or enroller role's password

The enroller reads its two password files whenever it opens a new database
connection, in the same way as the app
([rotate the app role's password](postgres-accounts.md#rotate-the-app-roles-password)).
It keeps its connections open between passes, so a connection it already has
keeps working after the role's password changes, and the new password is first
used when it reconnects, for example after a restart. Change the Secret first
and the role second, one role at a time:

1. Save `before.json` with `check_credentials`: `"passed": true`, and the
   copy's `"role_status": "limited"`.
2. Make a new password and write it to the Secret that holds the role's
   password file for the enroller (`KEEPLANE_GUARD_STATUS_DATABASE_PASSWORD_FILE`
   for a status role, `KEEPLANE_DATABASE_PASSWORD_FILE` for the approvals
   role, which every copy's enroller uses), with the commands of step 1 of
   [rotate the app role's password](postgres-accounts.md#rotate-the-app-roles-password).
3. Wait until the file has reached the enroller: its SHA-256 inside the
   enroller container matches your new file, as in "Before and after every
   rotation" of that page.
4. Change the role's password with `\password <role>`, as in step 3 of that
   section.
5. Restart the enrollers that use the role, one copy at a time, so they
   connect with the new password. After each restart, the enroller's log
   shows no "Model enrolment did not complete" line.
6. Save `after.json`: `"passed": true`, the copy's `"role_status"` still
   `limited`, and its `"guard"` and `models` unchanged.

If an enroller can't connect, for example because its Secret holds a different
password from the role, it logs "Model enrolment did not complete" on every
pass and records nothing, so its copy keeps its last confirmation; a model
changed meanwhile is refused through that copy until the enroller connects
again. Put the password you set on the role into the Secret, then restart that
enroller. Changing a password changes no grant, so you don't need to run
`configure_guard_status_access` again; run it again only after a role is
renamed or recreated.

## What you'll see

- While an enroller swaps a copy's checks, or after a swap on that copy fails,
  its row says nothing is confirmed and protected calls through that copy are
  refused until the next pass succeeds (every 2 seconds). A pass that fails
  before changing anything, for example while the gateway can't be read, keeps
  the copy's last confirmation.
- An edited or removed model waits about 3 minutes 16 seconds before its new
  check is in place, as in the Docker preview; the row keeps the old
  confirmation meanwhile, and the app refuses the changed model.
- A stopped enroller leaves its copy's last confirmation in place until a model
  changes; after that, its copy refuses protected calls until it runs again.

How the app checks a copy is described in
[runtime authorization](../architecture/runtime-authorization.md#per-copy-guard-status).
The `check_credentials` lines are covered by GS-26 and GS-PG-11 to GS-PG-14 in
[the guard-status cases](../../tests/integration/guard-status-cases.md).
These checks have been tested against PostgreSQL and simulated gateways; the
enroller container in each gateway copy Pod, and a live Kubernetes run, are
still to come.
