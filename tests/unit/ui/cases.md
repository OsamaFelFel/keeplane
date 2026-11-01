# React UI unit cases

Run `npm run test:unit` from `components/admin-ui/`. Vitest discovers test
files in this top-level `tests/unit/ui/` directory; component source has no
colocated tests.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| UI-01 | Open Create user, enter a too-short username and password, then submit. | Developer is selected by default, validation explains both inputs, and no request reaches the account API. |
| UI-02 | Create an Admin. | One protected request carries the chosen role and an operation ID; the dialog reports the new user. |
| UI-03 | Create a user when Keeplane doesn't answer, then choose Check, which finds it. | Nothing changes before 10 seconds; at 10 seconds the dialog says it isn't clear whether the user was created, that Keeplane didn't answer in time, and offers Check and Cancel; Check closes it with the user. The write is not repeated. |
| UI-04 | Lose the answer, choose Check, which finds nothing, then send again. | The dialog says Keeplane didn't answer in time. After Check the form shows what was typed, including the role, and the second request reuses the operation ID. |
| UI-05 | Create user gets a 500, 502, 503 or 504. | The dialog says it isn't clear whether the user was created and "Keeplane couldn't confirm the result. Check to find out.", and offers Check instead of saying nothing was saved. |
| UI-06 | Create user gets a success answer that names no user. | The dialog says Keeplane couldn't confirm the result, offers Check and reports no user. |
| UI-07 | Keeplane refuses the user, for example a taken name, then the admin edits the username. | The dialog says "[Username] wasn't created" with the username Keeplane refused, keeps what was typed and offers no Check. The title keeps naming the refused username while the field changes. |
| UI-08 | Keeplane refuses a 64-character username, the longest allowed. | The title names the whole username, not shortened, and may break inside it to wrap within the dialog, as table text wraps in the design system. |
| UI-09 | Keeplane refuses the user, or answers with a server error. | "[Username] wasn't created" and "It isn't clear whether [Username] was created" each show a circle-alert icon and a weight-600 title, as in `Users-create-failed.dc.html` and `Users-create-no-answer.dc.html`. |
| UI-ROLE-01 | Change a Developer to Admin while Keeplane refuses it, for example "Account not found". | The dialog stays open with Admin still chosen and shows the design system's failure message: a circle-alert icon, "[Username]'s role wasn't changed" at weight 600, then the reason as a sentence and "Nothing was saved. Check the details and try again." The change is sent once. |
| UI-ROLE-02 | Change a role while Keeplane answers with a server error, or doesn't answer. | The same failure message says "It isn't clear whether [Username]'s role was changed", then "Keeplane couldn't confirm the result." (server error) or "Keeplane didn't answer in time." (no answer), then "Save the role again to make sure; it won't be changed twice."; it doesn't say nothing was saved. Save role stays available. |
| UI-SIGN-01 | Open sign-in while no single sign-on provider is connected. | Only username, password and Sign in appear, with "No account? Ask your admin."; there is no single sign-on or sign-up control. |
| UI-SIGN-02 | Open sign-in while the server reports a connected provider. | Sign in with single sign-on also appears, and the note reads "No account? Signing in with single sign-on creates one. For a username and password, ask your admin." |
| UI-SIGN-03 | Open sign-in. | The Keeplane mark and name come first, then the title "Sign in". |
| UI-SIGN-04 | Sign in with a wrong password. | "The username or password is wrong." shows as a failure message with a circle-alert icon and a weight-600 line. |
| UI-USERS-01 | Open Users with the break-glass admin and a local user. | The break-glass row says it is managed at infrastructure level and has no action; other rows have Change role; there is no edit or remove action. |
| UI-USERS-02 | Choose Next, then search. | Next asks for page 2; search asks the server for matches from page 1, 25 at a time. |
| UI-CSRF-01 | Submit a browser change. | A fresh masked token is sent with same-origin credentials and the original JSON headers. |
| UI-CSRF-02 | Fail token bootstrap. | No mutation request is sent. |
| UI-CSRF-03 | Refuse or disconnect a mutation. | The write is not repeated automatically. |
| UI-CSRF-04 | Supply a different-origin URL. | No token or request is sent to that origin. |
| MO-UI-COUNT | Open Models with zero, one and two personal-key registrations. | Each personal row shows its server count below “Each developer's own”; shared models show no count. |
| CL-UI-01 | Open Models with two levels on Keeplane's pick and one changed by an admin. | The Complexity table marks each model “Keeplane's pick” or “changed by an admin”. |
| CL-UI-02 | Change Simple to another model. | The dialog offers only set-up models, names Keeplane's pick, disables Use Keeplane's pick for a level on Keeplane's pick, sends one protected request and shows the change. |
| CL-UI-03 | Choose Use Keeplane's pick on an admin-changed level. | The request sends no model and the page says the level uses Keeplane's pick again. |
| CL-UI-04 | The server refuses a level change. | The dialog stays open with the reason. |
| CL-UI-05 | Choose Remove model for a model an admin-changed level uses. | “[model] is still in use” lists “Complexity level: Complex”; no removal request is sent. |
| CL-UI-06 | A level was changed to a model after the page loaded, then the admin removes it. | The server's 409 opens the same in-use dialog with the level it names. |
| CL-UI-07 | No model is set up. | Each level says “No model set up yet” and Change is disabled. |
| CL-UI-08 | An admin's model isn't set up now. | The row explains that the admin's model isn't set up. |
| PR-UI-01 | Open Models with a rule for the Architect. | The Persona rules table shows “Persona is Architect” and its model. |
| PR-UI-02 | Add a rule for Frontend. | The dialog offers Architect, Developer and Frontend and only set-up models, keeps Add rule disabled until a model is chosen, sends one protected request and shows the new rule with a notice. |
| PR-UI-03 | Open Add rule with Architect, which already has a rule, then choose Developer. | The dialog says the new rule replaces Architect's current model; the note goes away for Developer. |
| PR-UI-04 | The server refuses the rule. | The dialog stays open with the reason. |
| PR-UI-05 | Remove a model the Architect rule uses. | The in-use dialog lists “Persona rule: Architect” and no level; no removal request is sent. |
| PR-UI-06 | A rule was added after the page loaded, then Remove model is confirmed. | The server's 409 opens the in-use dialog with “Persona rule: Frontend”. |
| PR-UI-07 | No rules; a rule whose model isn't set up; no set-up model. | “No persona rules yet”; the row says the rule sends no work; Add rule is disabled. |

## Projects

- Admins can see project names, onboarding state and who used each project.
- Class columns disappear while classes are off.
- Search returns to the first bounded page; Previous and Next follow server results.
- Empty and unavailable states are clear. Failed reloads do not leave stale rows visible.
- Set class submits the explicit choice through the protected action, including React StrictMode.
- A refused write keeps the choice. A lost reply or ten-second timeout offers Check without repeating the write.
- Readback confirms the saved class. If classes were turned off, the dialog keeps the result uncertain rather than clearing an assignment.

## Personal data in requests (`DataClassesDetection.test.tsx`)

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| DC-UI-05 | Open Data classes with classes on and detection never changed. | The Personal data in requests section shows the switch off and Confidential under Handle it as. |
| DC-UI-06 | Turn detection on, then choose Internal. | Each change sends one protected request with the switch and class, and a notice confirms it. |
| DC-UI-07 | Open Data classes with classes off. | The detection section is hidden. |
| DC-UI-08 | Open Data classes when the detector isn't installed or the install doesn't send messages. | The switch is disabled and the page says "Personal-data detection isn't installed. Install it, then turn this on." |
| DC-UI-09 | The detector disappears after detection was turned on. | The switch can still be turned off. |

The sign-in card title's size, `page-title` 28px on 36px at 600, is checked in a real browser by BR-13 in `tests/browser/users-cases.md`; the rest of the card's look and the failure message's look by BR-15 and BR-16.
