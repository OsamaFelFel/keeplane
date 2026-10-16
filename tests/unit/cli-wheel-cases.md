# CLI wheel cases

| Case | Expected result |
| --- | --- |
| Offline build and fresh virtual environment install | No package index or runtime dependency required; source tree absent from import paths. |
| Wheel contents and metadata | Only Keeplane modules, two instruction plugin resources and package metadata; original Apache license retained. |
| Installed executable | Main, login/device, refresh and coding help retain the existing flags. |
| Installed device/profile/refresh/logout commands | Actual synthetic HTTP exchange, correct fixed client and current actor; private state and redacted output. |
| Installed instruction plugin lookup | Adapter-relative installed files exist under the new environment and match source hashes. |

CI installs the hash-pinned backend and explicitly sets
`KEEPLANE_CLI_BUILD_PYTHON`; a configured missing/broken builder fails the test.
Local runs without that optional build environment skip it. No model/native
runtime, browser UI or live Django issuer is used in this packaging control.
