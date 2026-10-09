# Full local regression — 9 October 2026

**Edition:** Open Source. The new [runner](../run_regression.py) ran from clean
local commit `1de1102a613f` against the Docker preview, protected account
preview, and isolated `kind-keeplane` cluster. Its
[machine result](2026-10-09-full-regression.json) records the commands, Git
commit, stack-lock checksum, case IDs, verdicts, and timings.

**Result: 24/24 suites passed, 120/120 case records passed.** The runner found
no missing or unexpected case IDs. This includes real local Qwen answers,
gateway replica failover, protected model removal, account and class policy,
audit, and Docker/kind runtime limits. Individual suite reports were written
to a temporary directory; earlier committed evidence was not overwritten.

After the run, Docker and kind `/health` returned HTTP 200. The protected
preview returned its expected HTTP 302 sign-in redirect. All six pods in the
`keeplane` kind namespace were Running and Ready. The
[plain-English regression catalog](../regression-cases.md) lists the covered
areas and their source cases.

This baseline covers the functionality currently implemented in the local
preview. It does not certify real cloud subscriptions, the future developer
CLI, smart routing, a production gateway artifact, restricted runtime egress,
or the full Release 1 user journeys.
