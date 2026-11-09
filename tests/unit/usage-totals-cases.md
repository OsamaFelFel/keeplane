# Usage report rules

Spec 009 ST31, ADR 029, task 009-08. Run
`.venv/bin/python -m pytest tests/unit/test_usage_totals.py`. The HTTP and
database cases are in [developer usage](../integration/developer-usage-cases.md).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| DU-U1 | Check a valid report with an extra prompt field. | Only the four counts are kept. |
| DU-U2 | Check reports with negative, fractional, text, true/false or missing counts, or zero requests. | Each is refused. |
| DU-U3 | Check reports with huge numbers. | Requests are capped at 10,000; requests without tokens at the request count; tokens at 10 million per request that reported tokens. |
| DU-U4 | Work out what to delete in mid-November, just after the UTC month changes on 1 December (03:00 and 11:59), at 12:00 on 1 December, on 1 January and on 31 March. | The current month is taken at UTC-12; totals before the start of the month before it, at UTC+14, go. At 1 December 03:00 UTC all of October is kept, because New York is still in November; from 12:00, when UTC-12 reaches December, October goes. Reports count in the UTC hour they arrive in. |
| DU-U5 | Work out today and this month in UTC, at UTC+14, in India (UTC+5:30), Nepal (UTC+5:45), Chatham (UTC+13:45), Newfoundland (UTC-3:30, and -2:30 in summer) and in Berlin on the night summer time ends. | Each day and month starts at the UTC hour nearest that zone's local midnight, at most 30 minutes away. Nepal's day starts at 18:00 UTC. On a half-hour tie (India, Newfoundland) the earlier hour is used. |
| DU-U6 | Check time zone names. | No name means UTC; real names with up to three parts are accepted; unknown, path-like, empty, too long and non-text names are refused. |
