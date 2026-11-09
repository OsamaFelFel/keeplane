# Preview launcher: CLI sign-in and the guarded gateway by default

**Edition:** Open Source. Spec 009 ST29 and ST30, task 009-01, ADR 028.
[`test_preview_sign_in_launcher.py`](test_preview_sign_in_launcher.py) runs
`deploy/local/up.py`'s `main()` with Docker, Node.js and the containers
substituted, reads the Dockerfile, and renders the Compose files with
`docker compose config`, which starts nothing.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| PSL-01 | Run `python3 deploy/local/up.py` with no options. | It builds and starts the preview, checks the admin sign-in, then installs the protected runtime with no named models on port 5000 (the enroller enrols every saved approval) and checks the app again. It prints the earlier-database notice before the ready line, the enroller's report, `Keeplane is ready: http://127.0.0.1:3000`, `Guarded model gateway for the CLI: http://127.0.0.1:5000/v1` and `Sign in from the CLI: keeplane login --server http://127.0.0.1:3000 --profile PROFILE`, then the first-admin details as before. |
| PSL-02 | Pass `--runtime-model ID` or `--runtime-app-image IMAGE`. | Usage error (exit 2): the options no longer exist, and nothing starts. |
| PSL-03 | Start with `--port 3080 --runtime-port 5001`, then with both ports the same. | The gateway port is saved in the configuration file (`KEEPLANE_RUNTIME_PORT=5001`), used for the install and printed; the same port twice is refused. |
| PSL-04 | The protected runtime fails to start. | The launcher stops with the installer's error and never says Keeplane is ready. |
| PSL-05 | Read the Dockerfile. | The last stage, which `docker build` and Compose build by default, is `preview`. It and `detection` start from one `sign-in` stage that installs `requirements-cli-auth.txt` with `--only-binary=:all: --require-hashes --no-deps`, removes the build-only Python installers and ends as user 65532. The `cli-auth-trial` target is gone, and no image stage turns sign-in on. |
| PSL-06 | Render the preview's Compose files, as is and with `KEEPLANE_RUNTIME_OAUTH_ENABLED=0`. | The app and the runtime installer always get `KEEPLANE_CLI_OAUTH_ENABLED=1`; the guarded gateway publishes port 5000 on `127.0.0.1` only; the model enroller runs. |
| PSL-07 | Render the preview's Compose files, as is and with `KEEPLANE_RUNTIME_PORT=5001` (task 009-02, ADR 030). | The app gets `KEEPLANE_GATEWAY_PUBLIC_URL=http://127.0.0.1:5000/v1`, or `…:5001/v1` with the other port, the same port the guarded gateway publishes; the runtime installer and the model enroller don't get it. |
