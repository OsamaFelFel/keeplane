# Usage report rules

Spec 009 ST31, ADR 029, task 009-08. Run
`.venv/bin/python -m pytest tests/unit/test_usage_totals.py`. The HTTP and
database cases are in [developer usage](../integration/developer-usage-cases.md).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| DU-U1 | Check a valid report with an extra prompt field. | Only the four counts are kept. |
| DU-U2 | Check reports with negative, fractional, text, true/false or missing counts, or zero requests. | Each is refused. |
| DU-U3 | Check reports with huge numbers. | Requests are capped at 10,000; requests without tokens at the request count; tokens at 10 million per request that reported tokens. |
| DU-U4 | Work out what to delete in mid-November, on 1 January and on 31 March. | Totals before the start of the previous month at UTC+14 go, so the previous month is whole in every zone. Reports count in the UTC hour they arrive in. |
| DU-U5 | Work out today and this month in UTC, at UTC+14, in India (half-hour offset) and in Berlin on the night summer time ends. | Each day and month starts at that zone's own local midnight. |
| DU-U6 | Check time zone names. | No name means UTC; real names with up to three parts are accepted; unknown, path-like, empty, too long and non-text names are refused. |
