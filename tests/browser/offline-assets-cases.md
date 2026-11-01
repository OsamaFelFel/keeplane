# Web UI on an isolated network

**Edition:** Open Source; the same rule applies to Enterprise.
**Spec:** 002 Self-hosting, ST2 "The web UI loads from inside" (ADR 009).

Each case blocks and records every browser request, including web sockets, that
is not to the Keeplane address under test. It runs at 1280px and at 320px
against the live application with its real sign-in.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| OFF-UI-01 | Open the sign-in page with everything outside Keeplane blocked. | Nothing was blocked and no Keeplane asset failed. The heading, field labels and Sign in button are set in IBM Plex Sans at the design weights (600, 500, 600), and the browser reports it drew each with the matching bundled file: semibold, medium, semibold. The regular, medium and semibold Sans files and the Mono file load from Keeplane with status 200. The page fits the width. |
| OFF-UI-02 | Sign in as the first admin and open Models and routing with everything outside Keeplane blocked. | The same as OFF-UI-01, checked on the page heading (semibold), its description (regular) and the first button in the page (medium). |

A face a page does not draw is loaded on request: the Mono file on both pages,
which show no code text, and the regular Sans file on sign-in. This still proves
Keeplane serves every declared file. A weight drawn with a neighbouring file or a
synthesized face fails, because the browser reports the file that drew the text. The [static cases](../unit/ui-offline-assets-cases.md)
check the build for external addresses.

Run `npm test -- offline-assets.spec.ts` from this directory with the
application running. Set `KEEPLANE_BASE_URL` for another address.
