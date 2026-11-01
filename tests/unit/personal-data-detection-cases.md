# Personal-data detection rules

Spec 005 ST20. Run `python -m pytest tests/unit/test_personal_data_detection.py`.
A deterministic fake stands in for the language model, so these run anywhere;
[the model cases](../integration/personal-data-model-cases.md) check the real
one. Every value is invented: fiction-range phones, `example.com` emails.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| PD-01 | Check 16-digit numbers from 2221 to 2720, plain or grouped, and numbers just outside or failing Luhn. | Only Luhn-valid numbers in the Mastercard 2-series range are cards. |
| PD-02 | Check IP addresses, build and version numbers, and real phones after words such as Build, version, Job or Rev. | IPv4 addresses and build-shaped numbers after `build`, `version` or `v` are not phones; numbers starting with 0 or +, North American shapes and phones after any other word stay phones. |
| PD-03 | Check names and places in backticks, stack traces, imports, package paths, time zones and the allow list, and names in prose, string literals and comments. | Code-explained names and places are dropped; names in prose, literals and comments are kept; email, phone and card findings are never dropped. |
| PD-04 | Check a long request: a value across a piece boundary, personal data in the first piece, and a fenced code block spanning many pieces. | Pieces overlap and cover every character; the value is found; the check stops after the first piece with personal data; code context comes from the whole request. |
| PD-05 | Check a request with a name, a clean request and one with a 2-series card. | The name and card hold the request; the clean one passes. |
| PD-06 | Make the detector slower than the limit, give it a request it cannot finish in time or one over 100 000 characters, make it raise, leave it loading or fail to install, and send no text. | Every case holds the request, with a reason naming why; a slow check answers within the limit. |
| PD-07 | Read a chat request with system, user text parts, tool calls, tool results, legacy `function_call`, refusals and refusal parts; then images, wrong types, broken or non-list tool calls, and unknown fields such as `audio` or `metadata` that carry a value. | All text is read; anything unreadable or unknown makes the request not checked, so it is held, never an error. |
| PD-08 | Check requests with an email, including one whose detector error message contains it. | No request text appears in logs or verdicts. |
| PD-09 | Compare `requirements-detection.txt` with the licence inventory (`test_detection_inventory.py`). | Every pin has the same version and hash in the inventory and a source address; Presidio 2.2.364, spaCy 3.8.18 and `en_core_web_lg` 3.8.0 are pinned; the supplemental Presidio MIT notice matches its hash. |
| PD-10 | Read the app Dockerfile. | One build stage installs the detector, with hashes and its notices, and only the explicit `detection` (SQLite), `postgres-detection` and `postgres-cli-auth-detection` targets copy it in; each names the bundled model, none sets the install setting, none ends as root, and the default image is unchanged. |
| PD-11 | Build the managed gateway's entry and selected-model checks (`test_runtime_config.py`) with and without the install setting for detection. | By default both checks carry exactly the metadata they carried before detection. With the setting, both also send `messages` behind a 1 MiB size guard; operator validation never does. |
| PD-12 | Ask whether the detector is still starting while its first load runs, after it loads, after a failed first load and during the retry a minute later, and after a first load that hangs past the start wait (`test_personal_data_detection.py`). | Starting only while the first load runs and for at most the start wait (300 seconds); asking starts the load. A failed load or a later reload never counts, so the app is not taken out of service and requests it can't check are held instead. |
| PD-13 | Probe readiness and start an app process with the install setting off, on with the detector loading, on with it loaded, and on in an image without the detector (`test_readiness.py`). | Off: readiness is unchanged and nothing loads. On and loading: readiness answers 503 `starting`; loaded: 200. On without the detector: readiness answers 200, nothing loads, and the start-up log says the image has no detector and names the `detection` image targets; the log carries no request text. |

The UI cases DC-UI-05 to DC-UI-07 are in [the React UI cases](ui/cases.md).
