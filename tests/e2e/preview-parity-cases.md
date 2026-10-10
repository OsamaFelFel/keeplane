# Docker and kind protected-preview parity

Edition: Open Source. The full regression runs these checks against the protected Docker preview on port 3000 and the managed kind preview on port 13000. The two installations keep separate records, so matching behavior is required; identical account or model lists are not.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| PARITY-01 | Compare the backend source and built React application files inside both running app containers. | The same files have the same hashes; neither preview serves an older build. |
| PARITY-02 | Sign in as the first admin on both addresses and open Users, Data Classes, Audit and Models. | Each preview serves the protected UI and the same account, class, audit, model and gateway API shapes. |

The full regression also runs the existing account, class, audit, local and cloud model-management cases in both previews, followed by the real local Qwen gateway journey. See `regression-cases.md` for the complete command. This is local functional parity, not shared state or production authorization evidence.

Run the Chromium suite in `tests/browser/` on each address to check the visible React Users, Data Classes and Audit flows. The Audit and Users cases include a quick Next click after initial load so a search timer cannot reset the page. The browser run files are saved under `tests/browser/runs/`.
