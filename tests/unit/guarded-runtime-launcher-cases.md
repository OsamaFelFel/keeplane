# Opt-in managed launcher

Run `pytest tests/unit/test_guarded_runtime_launcher.py tests/unit/test_runtime_preparation.py`.
The cases check fresh process ordering, migration before the new app, current
operator hashes, stable callback credentials, disabled enrollment before file
validation, starting the private model enroller only after enrollment, and
stopping only the managed gateway and its enroller after setup or publication
failure. Stop errors are reported as unconfirmed. Unit ownership calls are
substituted because the host cannot chown files to the container account.

`docker compose -f compose.yaml -f deploy/local/runtime.yaml config --quiet`
checks the opt-in schema without starting anything. The default Compose file is
unchanged. Actual command/provider controls and the isolated installed CLI
journey validate runtime behavior separately; these unit tests do not claim a
full launcher or release deployment acceptance.
