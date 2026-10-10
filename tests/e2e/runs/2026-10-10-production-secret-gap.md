# 10 October 2026 — gateway database secret gate

The [plain-English diagnostic](../production-package-cases.md), [probe](../test_production_package_gaps.py) and [boolean-only result](2026-10-10-production-secret-gap.json) inspected the pinned agentgateway standalone chart v1.6.0 as bundled in Keeplane. With the disposable local PostgreSQL URL, the rendered gateway ConfigMap contains the password-bearing connection URL. The probe does not save or print that URL. The release expectation fails; the passing local chart and product regressions do not override it.

The bundled upstream chart's `renderedConfig` helper inserts `database.postgres.url` into `config.database.url`, and its ConfigMap template renders that configuration. The chart validates that a database URL is present in database mode. Its `extraEnv` and `extraVolumes` hooks do not, by themselves, remove the URL from the ConfigMap. A release package needs a tested Secret-backed database configuration from the selected gateway chart or a different supported deployment route; placing a production password in the current value is not acceptable.

This diagnostic does not change either preview or select a release gateway. The local PostgreSQL service and its password remain disposable fixtures.
