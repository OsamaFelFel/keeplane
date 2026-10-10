# React Audit local trial — 2026-10-10

**Edition:** Open Source local trial. Source branch: `feat/react-audit`, based on `209dd88`. Tests ran against the local Docker preview and the isolated kind integration cluster. No product-team-owned file or constitution changed.

## What works now

- The protected Audit screen is in the shared React shell at `http://127.0.0.1:3000/app/audit`. The earlier Audit HTML and JavaScript were removed; `/audit` redirects to the React route.
- Three optional recording controls read and save their own state. The break-glass sign-in control is checked and disabled. Failed writes return the visible control to the confirmed state.
- Search, record kind, and pagination use the protected records API. A failed read shows an error without presenting stale rows as the new result.
- The supplied Audit design is represented by shared shadcn components and native controls. The 320px layout keeps horizontal table scrolling inside the table frame.

| Check | Outcome |
| --- | --- |
| [Plain-English browser cases](../../browser/audit-cases.md) | 13/13 combined Chromium cases passed, including four Audit cases for switch state, persistence, search/filter/paging, error handling, desktop, and 320px screenshots. |
| [Focused live Audit run](2026-10-10-react-audit-focused.json) | 2/2 suites, 12/12 case records passed for the Audit API and break-glass sign-ins. |
| [First full regression](2026-10-10-react-audit-full-final.json) | 31/32 suites passed. The kind existing-gateway preflight failed when its supplied gateway model-management read exceeded the eight-second client timeout; the gateway pod stayed healthy. The failed Job returned `Gateway model-management read API is unavailable`, and its gateway request log showed an 8004 ms read with no completed HTTP status. |
| [Preflight recheck](2026-10-10-react-audit-preflight-recheck.json) | 1/1 suite, 4/4 cases passed on the same local cluster without changing code or configuration. |
| [Clean full regression](2026-10-10-react-audit-full-recheck.json) | 32/32 suites, 169/169 case records passed across Docker, kind, Qwen, accounts, model setup, gateway modes, Audit, and the integrated demo. The runner restored the initial data-class mode. |
| React unit test, TypeScript/Vite build, lint | Unit test and build passed; lint passed with existing non-blocking React compiler/TanStack warnings. |

The [desktop screenshot](../../browser/audit.spec.ts-snapshots/audit-1280-darwin.png) and [320px screenshot](../../browser/audit.spec.ts-snapshots/audit-320-darwin.png) are versioned with the browser cases. The preview also remains available in kind at `http://127.0.0.1:13000`; its account and Audit APIs are not yet the protected Docker integration.

The settings producer currently records Keeplane model setup/removal and data-class changes. Held-back-request and model-answer controls can be saved, but their event producers are still separate work. Production shared storage, retention, and the release gateway choice are also open. This trial does not claim those scenarios complete.
