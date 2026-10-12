"""Render PostgreSQL deployments and reject incomplete or conflicting settings."""

import json
from test_chart_package import CHART, case, named, run


def main():
    base = ("--set", "app.postgres.enabled=true", "--set", "app.replicaCount=2",
            "--set", "app.postgres.host=db", "--set", "app.postgres.database=keeplane",
            "--set", "app.postgres.user=app", "--set", "app.postgres.credentialsSecret=app-db",
            "--set", "app.postgres.identitySecret=identity", "--set", "app.postgres.caSecret=ca",
            "--set", "app.postgres.publicOrigin=https://keeplane.example.test",
            "--set", "app.postgres.providerKeysClaim=provider-keys",
            "--set", "app.postgres.migration.user=migrate",
            "--set", "app.postgres.migration.credentialsSecret=migrate-db",
            "--set", "gateway.keysSecret=gateway-keys",
            "--set", "agentgateway-standalone.mode=readonly")
    managed = run("template", "pg", CHART, *base)
    existing = run("template", "pg", CHART, *base, "--set", "gateway.mode=existing",
                   "--set", "gateway.install=false", "--set", "gateway.url=http://customer:4000")
    app = named(managed.stdout, "Deployment", "pg-app")
    job = named(managed.stdout, "Job", "pg-accounts-migrate")
    rows = [case("PGCHART-01", managed.returncode == existing.returncode == 0 and
                 "replicas: 2" in app and "name: KEEPLANE_DATABASE_HOST" in app and
                 "ACCOUNT_DB" not in app and not named(managed.stdout, "PersistentVolumeClaim", "pg-state")
                 and not named(existing.stdout, "Deployment", "pg"),
                 {"managed_exit": managed.returncode, "existing_exit": existing.returncode})]
    missing = {}
    for field in ("host", "database", "user", "credentialsSecret", "identitySecret", "caSecret", "providerKeysClaim"):
        result = run("template", "pg", CHART, *base, "--set", "app.postgres." + field + "=")
        missing[field] = result.returncode
    rows.append(case("PGCHART-02", all(missing.values()), {"incomplete_configuration_exits": missing}))
    rows.append(case("PGCHART-03", bool(job) and 'secretName: "migrate-db"' in job and
                     'secretName: "migrate-db"' not in app and 'secretName: "app-db"' in app and
                     "first-admin-password" not in job and "pre-install,pre-upgrade" in job and
                     "readOnlyRootFilesystem: true" in job and "automountServiceAccountToken: false" in job,
                     {"migration_job_present": bool(job), "migration_password_mounted_in_app": 'secretName: "migrate-db"' in app}))
    conflict = run("template", "pg", CHART, *base, "--set", "app.localTrial.enabled=true")
    shared_role = run("template", "pg", CHART, *base, "--set", "app.postgres.migration.user=app")
    shared_secret = run("template", "pg", CHART, *base, "--set", "app.postgres.migration.credentialsSecret=app-db")
    sqlite_replicas = run("template", "pg", CHART, "-f", "deploy/local/values.yaml", "--set", "app.replicaCount=2")
    rows.append(case("PGCHART-04", all(result.returncode for result in (conflict, shared_role, shared_secret, sqlite_replicas)),
                     {"conflict_exit": conflict.returncode, "shared_role_exit": shared_role.returncode,
                      "shared_secret_exit": shared_secret.returncode, "sqlite_replicas_exit": sqlite_replicas.returncode}))
    insecure = run("template", "pg", CHART, *base, "--set", "app.postgres.publicOrigin=http://localhost")
    rows.append(case("PGCHART-05", insecure.returncode != 0 and all(
                     "value: verify-full" in manifest and "ca.crt" in manifest and "defaultMode: 0440" in manifest
                     for manifest in (app, job)) and "path: /health/ready" in app and "path: /health/app" in app,
                     {"insecure_origin_exit": insecure.returncode, "verified_database_tls": "value: verify-full" in app}))
    external = run("template", "pg", CHART, *base, "--set", "app.postgres.migration.enabled=false")
    rows.append(case("PGCHART-06", external.returncode == 0 and not named(external.stdout, "Job", "pg-accounts-migrate"),
                     {"externally_migrated_render_exit": external.returncode}))
    print(json.dumps({"suite": "PostgreSQL chart contract", "results": rows}, indent=2))
    return int(any(row["verdict"] != "pass" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
