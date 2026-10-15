# Optional data classes local trial — 2026-10-10

**Edition:** Open Source local trial. Source branch: `feat/optional-data-classes`, based on `4783470`. The full run began at 01:50 UTC while the source was uncommitted, then finished at 01:55 UTC. Its [JSON report](2026-10-10-optional-data-classes-full-final.json) records the source branch, stack lock and each case. No product-owned file or constitution was changed.

## What works now

- A fresh protected Docker settings store starts with classes off. Turning the mode on creates Public, Internal and Confidential once. Turning it off keeps definitions and approvals; turning it back on restores only the approvals the admin actually made.
- Model setup and class approval are separate. A model set up with no class while the mode is off stays set up, but receives no automatic approval when classes are enabled. Removing its last approval does not delete its setup.
- The React Data Classes screen uses the shared shadcn theme. The Models screen hides its class column and inputs while the mode is off. Class mode changes are recorded when Audit settings recording is enabled.
- The old Data Classes HTML/JS page was removed. The kind integration trial, which does not yet expose the protected settings API, still loads its Models page.

| Check | Outcome |
| --- | --- |
| [Full regression](2026-10-10-optional-data-classes-full-final.json) | 32/32 suites, 169/169 case records passed across Docker, kind, real Qwen, accounts, models and Audit. The runner restored the original off mode. |
| [Focused run after final Docker restart](2026-10-10-optional-data-classes-focused-final.json) | 4/4 suites, 21/21 case records passed: storage, Audit, live Data Classes and model registration. The Audit storage suite ran four internal checks. |
| [Plain-English class cases](../data-classes-cases.md) | CLASS-00 and CLASS-10 verify off mode and no implicit approval; CLASS-09 verifies on/off/on retention. All 11 live class cases passed. |
| [Browser cases](../../browser/data-classes-cases.md) | 9/9 total Chromium cases passed, including the three new Data Classes and Models controls cases. [Off](../../browser/data-classes.spec.ts-snapshots/data-classes-off-1280-darwin.png) and [on](../../browser/data-classes.spec.ts-snapshots/data-classes-on-1280-darwin.png) desktop screenshots are versioned; the 320px page has no document-wide horizontal scroll. |
| Kind Models smoke | After redeployment, Chromium saw `local-fixture` and an enabled Add model button at `127.0.0.1:13000` with no Data Classes API. |

The Docker preview remains available at `http://127.0.0.1:3000/app/data-classes`; the kind integration preview remains at `http://127.0.0.1:13000`. The protected Docker trial uses SQLite. The kind app still lacks protected account/settings integration, so this evidence does not close the production managed or existing-gateway paths. Project class enforcement and personal-data detection are separate tasks 005-02 and 005-03. The release gateway remains unselected.
