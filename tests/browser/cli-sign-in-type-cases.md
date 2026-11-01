# CLI sign-in pages follow the design type scale

**Edition:** Open Source; the same pages serve Enterprise.
**Spec:** 002 ST2, Keeplane needs nothing from the internet to run (task 002-03), and
003 ST6 sign-in, whose developer scenario points developers to the CLI sign-in
(task 003-03); the CLI sign-in itself is the ADR 022 trial.
**Design:** `product/design/system/tokens.json` text styles and `components.md`
(Components, Field sizes, Errors, Narrow screens) in the governance repository;
the sign-in card in `product/design/canvas/Main.dc.html`, the field error in
`Users-create-failed.dc.html`, the failure message in `Main-failed.dc.html` and the
command style in `Web-UI-developers.dc.html`.

The CLI consent and device-code pages are Django templates served only by the
optional ADR 022 trial. Each case renders every page state with Django's own
template engine (`tests/support/render_cli_sign_in.py`, synthetic names). A code
Keeplane rejects, on the entry or the confirm screen, uses the same page context
as the running view (`accounts/cli_device_pages.py`). Each page is served with the bundled IBM Plex
files and every other request is blocked. Each case runs at 1280px and at 320px.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| CLI-TYPE-01 | Open each state: consent, consent refused, code entry, code rejected by Keeplane, code left blank, code confirm, code rejected on the confirm screen, access allowed, access cancelled. | The title is 28px on 36px at 600 (`page-title`). Body text is 15px on 22px at 400. "Signed in as" is 14px on 20px at 400 (`small`) with the name at 600. The field label is 14px on 20px at 500 (`field-label`), and a field error is 14px on 20px. The failure message's line is 15px on 22px at 600. The CLI code is IBM Plex Mono 14px on 20px at 400 (`code`). The text field is 15px on 22px; Cancel is 15px on 22px at 500 and Continue at 600. Every other text is IBM Plex Sans. Each text on the page matches one of these styles. The semibold Sans file, and the Mono file where a code shows, loaded; nothing left the page and the page fits the width. |
| CLI-TYPE-02 | Open code entry and code confirm, and focus the code field. | The field is at least 44px tall, 6px under its label, with a 1px `control-border` edge and 6px corners; focus shows a 2px `ink` ring. Both buttons are at least 44px tall with 18px side padding and 6px corners. The CLI code sits on `ground` with a 1px `line` edge, 4px corners and 2px 6px padding. The card has 32px padding and 10px corners and is 400px wide, or the width less 16px each side on a narrow screen. |
| CLI-TYPE-03 | Open code entry after Keeplane rejects a code, and after a blank code. | The field is marked invalid and described by "Check the code shown in your CLI and try again.", which sits 6px under it with a 16px circle-alert icon. The field's edge becomes 2px `ink`. No failure message shows. |
| CLI-TYPE-04 | Open the confirm screen after its code is rejected. | A failure message above the buttons says "Check the code shown in your CLI and try again." on `ground`, with a 1px `control-border` edge, 8px corners, 14px 16px padding and a 20px circle-alert icon. |

The [device-flow integration case](../integration/test_cli_oauth_device.py)
`test_device_rejected_code_marks_the_field_and_links_its_error` checks the same
field marking on the page the running view returns, and
`test_device_claim_cannot_be_stolen_or_confirmed_by_another_account` checks that a
code rejected on the confirm screen returns status 400 with the confirm screen, its
failure message above the buttons and no code field.

Run `npm test -- cli-sign-in-type.spec.ts` from this directory. The cases need a
Python with Django (`pip install -r tests/requirements.txt`): set
`KEEPLANE_TEST_PYTHON`, or they use `.venv/bin/python` at the repository root,
then `python3`. They need no running application.
