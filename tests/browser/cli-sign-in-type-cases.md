# CLI sign-in pages follow the design type scale

**Edition:** Open Source; the same pages serve Enterprise.
**Spec:** 002 ST3 and 003 ST3 CLI sign-in (ADR 022 trial).
**Design:** `product/design/system/tokens.json` text styles and `components.md`
(Components, Field sizes, Errors, Narrow screens) in the governance repository.

The CLI consent and device-code pages are Django templates served only by the
optional ADR 022 trial. Each case renders every page state with Django's own
template engine (`tests/support/render_cli_sign_in.py`, synthetic names), serves
it with the bundled IBM Plex files and blocks every other request. Each case runs
at 1280px and at 320px.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| CLI-TYPE-01 | Open each state: consent, consent refused, code entry, code rejected, code confirm, access allowed, access cancelled. | Every text is set in IBM Plex Sans: the title 24px on 32px at 600; body text 15px on 22px at 400 and strong text at 600; the field label 14px on 20px at 500 (`field-label`); the text field 15px on 22px; Cancel 15px on 22px at 500 and Continue at 600. The semibold Plex file loaded, nothing left the page and the page fits the width. |
| CLI-TYPE-02 | Open code entry and code confirm, and focus the code field. | The field is at least 44px tall, 6px under its label, with a 1px `control-border` edge and 6px corners; focus shows a 2px `ink` ring. Both buttons are at least 44px tall with 18px side padding and 6px corners. The card has 32px padding and 10px corners and is 400px wide, or the width less 16px each side on a narrow screen. |
| CLI-TYPE-03 | Open code entry after a rejected code. | The field is marked invalid and its edge becomes 2px `ink`. |

The sign-in card title has no named text style; it uses 24px on 32px, the same
size as the web sign-in page's title.

Run `npm test -- cli-sign-in-type.spec.ts` from this directory. The cases need a
Python with Django (`pip install -r tests/requirements.txt`): set
`KEEPLANE_TEST_PYTHON`, or they use `.venv/bin/python` at the repository root,
then `python3`. They need no running application.
