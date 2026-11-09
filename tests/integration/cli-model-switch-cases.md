# The `keeplane use` switch on the real server

Spec 004 ST17 "My switch beats Keeplane's picks" (D150) and the persona-rule
decision on keeplane #178 ("A developer can't switch to a model the project
doesn't allow"). Journey: DEV-02, DEV-03. The CLI's own request code reaches
the real Django routes, accounts, policy and enrollment files of the
[task routing cases](task-routing-cases.md) through the test client. Run
`python -m pytest tests/integration/test_cli_model_switch.py`.

| Case | Expected result |
| --- | --- |
| CSW-01 Switch beats rule and level | With an Architect rule to `public` and Complex changed to `outside`, the rule decides without a switch. Sent as the route's `model_id`, the switch to `private` wins. |
| CSW-02 Code uses the saved switch | A switch saved in the settings file is the model `code` picks, with the "as you chose" notice; cleared, Keeplane's pick is used with its notice. |
| CSW-03 Not allowed | A model the project's class doesn't allow isn't in the list `keeplane use` checks. A switch saved before the class changed is refused, whether the CLI's list or the server's 403 catches it, and no rule replaces it. |
| CSW-04 Own key missing | A switch to `private` with the developer's key removed goes to the server's next model and says why; the switch stays saved. |
