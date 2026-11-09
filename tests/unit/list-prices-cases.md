# List-price table rules

Spec 009 ST31 (D186, D189), ADR 029, task 009-09. Run
`.venv/bin/python -m pytest tests/unit/test_list_prices.py`. The cases that read
cost over HTTP are DU-C1 to DU-C9 in
[developer usage](../integration/developer-usage-cases.md).

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| LP-U1 | Load the price list that ships with Keeplane. | It passes every check. Each row cites the provider's own https pricing page, and the list's date is its oldest row's checked date. Only OpenAI and Anthropic rows are listed. |
| LP-U2 | Check lists with a missing or extra field, another version or currency, a badly written or impossible date, no rows, an unknown provider, a model name with spaces or slashes, prices written as numbers, negative, in exponent form, with more than four decimals or of 10,000 dollars or more, a source that isn't the provider's own https page, a duplicate row, or a list date that isn't the oldest row's date; and an unreadable file. | Each is refused with a message naming the problem. A row checked after the list's date is allowed. |
| LP-U3 | Look up prices by provider and model name. | Only an exact match of both is found. Another provider, other letter case, extra spaces, a longer or shorter name are not. |
| LP-U4 | Work out costs for 0 tokens, 1 token, a mix and 10^15 tokens. | Tokens times the price per million, rounded half up to a millionth of a dollar, exact even for huge totals. |
| LP-U5 | Decide the cost status for a listed cloud model, an unlisted cloud model, a local model, a model whose provider wasn't recorded, and one with no approval. | Only the listed cloud model is priced (`estimate`). A local model is `local` even if its runner's model name matches a listed cloud model. The others are `no_list_price`. |
| LP-U6 | The shipped list can't be read. | No model is priced; local models stay `local`. |
