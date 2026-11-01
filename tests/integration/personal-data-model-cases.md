# The shipped detector against the release-1 bar

Spec 005 ST20. Needs the optional detector (Presidio Analyzer 2.2.364, spaCy
3.8.18 and `en_core_web_lg` 3.8.0, as pinned in
`components/control-plane/requirements-detection.txt`). Skipped when they are
not installed. Run it explicitly, keeping the output outside Git:

```sh
python -m pytest tests/integration/test_personal_data_model.py -m optional -s
```

The sets in `tests/fixtures/personal_data/` are copies of the fixed English
sets the bar was measured on; every value in them is invented. Do not tune the
rules on the held-out set.

| Case | Plain-English action | Expected result |
| --- | --- | --- |
| PM-01 | Check every request in the development set (`2026-10-31.1`) and the held-out set (`2026-10-31.h1`) through the shipped check, with its 200 ms limit. | Development: at most 4 of 120 personal-data requests missed and 1 of 240 clean requests held. Held-out: at most 11 missed and 14 held. Output is counts and case IDs only. |
| PM-02 | Check a request with an email while every network connection fails. | The request is held for personal data; nothing is downloaded or fetched, and the verdict names no text. |
