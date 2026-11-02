# The shipped detector against the release-1 bar

Spec 005 ST20. Needs the optional detector (Presidio Analyzer 2.2.364, spaCy
3.8.18 and `en_core_web_lg` 3.8.0, as pinned in
`components/control-plane/requirements-detection.txt`). Skipped when they are
not installed. Run it explicitly, keeping the output outside Git:

```sh
python -m pytest tests/integration/test_personal_data_model.py -m optional -s
```

The **detection image** CI job runs these cases inside the
`postgres-detection` image it builds, so they check the image's own detector
code and bundled model: no network, a read-only root filesystem and the
image's own user, with only the pytest runner, the tests and `pytest.ini`
mounted read-only. The job fails if any case is skipped or the bar is not
checked on both sets. The [detection image cases](detection-image-cases.md)
show how to build the image.

The sets in `tests/fixtures/personal_data/` are copies of the fixed English
sets the bar was measured on; every value in them is invented. Do not tune the
rules on the held-out set.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| PM-01 | Check every request in the development set (`2026-10-31.1`) and the held-out set (`2026-10-31.h1`) through the shipped check, with its 200 ms limit. | Development: at most 4 of 120 personal-data requests missed and 1 of 240 clean requests held. Held-out: at most 11 missed and 14 held. Output is counts and case IDs only. |
| PM-02 | Check a request with an email while every network connection fails. | The request is held for personal data; nothing is downloaded or fetched, and the verdict names no text. |
| PM-03 | Count, for each of the five kinds (name, address, email, phone, card), the personal-data requests of that kind in both sets and how many the shipped check misses. | Each kind has at least 20 requests in each set and none is missed more often than when the bar was measured: development 2 names and 2 addresses; held-out 4 names, 6 addresses and 1 card; no email or phone. Output is counts only. |
| PM-04 | Check the clean requests shaped like code: code, stack traces, imports, package paths, code in backticks or fences, command lines, configuration, logs, regions and time zones. | None is held, except at most 1 of the 23 held-out time zones, as measured. Output is counts only. |
