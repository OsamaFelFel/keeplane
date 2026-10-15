# Project usage records

The Django `projects` app stores a project's opaque ID, display name and use
times. A separate record links each account that has used it. A project can be
used before onboarding and without a data class.

```mermaid
flowchart LR
  Caller[Authenticated caller] --> Store[Project use service]
  Store --> Projects[(Projects)]
  Store --> Usage[(Account usage)]
  Admin[Signed-in admin] --> Listing[Project listing API]
  Listing --> Projects
  Listing --> Usage
  Listing --> Classes[(Class assignments)]
```

`DjangoProjectStore.register_use(user_id, project_id, name)` is an internal
service. Its caller must supply the account established by authentication.
It rechecks that account, records first use atomically and updates later use
without renaming the project. Repeated requests with the same ID do not create
another project. A storage failure rolls back both project and usage writes.

Existing class assignments stay in `data_classes.ProjectClass`. Recording use
does not assign a class, authorize a model or establish the origin of content.
The project ID is requested context supplied by the caller.

`GET /api/projects` is an internal admin read. It searches project names and
returns stable, bounded pages with the accounts that used each project. It
reads class assignments only while classes are enabled. It never returns
passwords or sessions and never changes project policy. There is no onboarding
completion writer yet, so current first-use records report `initialized: false`.

CLI registration, project access checks and the Projects screen are separate
changes.
