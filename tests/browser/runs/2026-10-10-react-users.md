# React Users browser and unit run — 2026-10-10

**Edition:** Open Source

**Branch:** `feat/react-users-stack`

**Code under test:** the working tree following `91f672b` (subsequently committed with this report)

**Environment:** local Docker preview at `127.0.0.1:3000`, macOS Chromium headless shell, Node 22.22.2; product design baseline `keeplane-governance` `a2a0397`.

| Check | Result | Evidence |
| --- | --- | --- |
| React build | Pass | `npm run build` in `components/admin-ui/web/`; IBM Plex files returned HTTP 200 as `font/woff2` from the local preview. |
| React lint | Pass with seven warnings | `npm run lint`; warnings concern React Compiler and shared shadcn component export patterns. No lint errors. |
| UI-01 | Pass, 1/1 | `npm run test:unit`; invalid account fields did not reach `fetch`. [Case](../../unit/ui/cases.md). |
| BR-01–BR-06 | Pass, 6/6 | `npm test` in `tests/browser/`; 18.6 seconds. The suite includes a real first-admin sign-in and fixed-response browser journeys. [Cases](../users-cases.md) and [desktop](../users.spec.ts-snapshots/users-1280-darwin.png), [narrow](../users.spec.ts-snapshots/users-320-darwin.png), [narrow menu](../users.spec.ts-snapshots/users-320-menu-darwin.png) screenshots. |
| Full implemented-feature regression | Pass, 30/30 suites and 157/157 case records | [Machine-readable run](../../e2e/runs/2026-10-10-react-browser-full.json), 00:54–00:59 UTC; Docker, kind, real local Qwen, accounts, models, audit and gateway journeys. Stack-lock SHA-256 `0b79e64e66897f37aed2dcc62ce62d75c10f9934dcfa547c8a9f67c4b1d0b5ec`. |
| Dependency advisory check | Pass | `npm audit --json` returned zero vulnerabilities for both the admin UI and browser-test lockfiles. |

The expanded browser run first exposed missing focus restoration after closing Create user. The UI now returns focus to the trigger, and BR-06 passes. A table-scroll assertion initially queried the outer table frame rather than shadcn's actual scroll container; the corrected assertion passes. The final run has no failed or skipped browser case.

The Docker Desktop engine stopped when local disk space filled during Playwright installation. It was force-stopped and restarted through the Docker Desktop CLI without deleting volumes. The existing Keeplane containers restarted, the preview returned HTTP 200, and the full regression passed after recovery. The browser install command now requests only the Chromium headless shell.
