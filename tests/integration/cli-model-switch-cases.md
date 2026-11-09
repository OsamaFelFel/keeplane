# The `keeplane use` switch on the real server

Spec 004 ST17 "My switch beats Keeplane's picks" (D150) and the persona-rule
decision on keeplane #178 ("A developer can't switch to a model the project
doesn't allow"). Journey: DEV-02, DEV-03. The CLI's own request code
(`server_connection.request`, with its query building and 401/403 handling)
reaches the real Django routes over HTTP on a threaded local server. The
accounts, policy and enrollment files are those of the
[task routing cases](task-routing-cases.md). Run
`python -m pytest tests/integration/test_cli_model_switch.py`.

| Case | Expected result |
| --- | --- |
| CSW-01 Switch beats rule and level | With an Architect rule to `public` and Complex changed to `outside`, the rule decides without a switch. Sent as the route's `model_id`, the switch to `private` wins. |
| CSW-02 Code uses the saved switch | A switch saved in the settings file is the model `code` picks, with the "as you chose" notice; cleared, Keeplane's pick is used with its notice. |
| CSW-03 Not allowed | A model the project's class doesn't allow isn't in the list `keeplane use` checks. A switch saved before the class changed is refused, by the CLI's list or by the server's 403 over HTTP, and no rule or level replaces it. |
| CSW-04 Own key missing | A switch to `private` with the developer's key removed goes to the server's next model and says why; the switch stays saved. |
| CSW-05 The list's marks | `keeplane models` marks Keeplane's pick, then the switch (`you`). With the own key gone it marks the model the next task really uses (`keeplane`) and says why. A switch the project no longer allows marks nothing and is named. |
| CSW-06 Project refused | A 403 that isn't about the model keeps the server's reason: "This project is unavailable. Nothing was sent." |
| CSW-07 Ended sign-in | The server's 401 is reported as an expired sign-in. |

The OAuth, device and rendered-browser journeys keep the settings file in the
test's own folder and check the exact `models` output: the journey servers
list the model but have no gateway that can take it, so nothing is marked and
`"chosen_by"` is null.
