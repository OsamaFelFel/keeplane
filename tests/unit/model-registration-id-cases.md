# Model registration ID cases

| Case | Expected result |
| --- | --- |
| Add local fixture/runner, OpenAI or Anthropic model | Native value has `id` equal to its API model ID; full value/revision fingerprint approved. |
| Replace shared key | Temporary verification model has its own unique name and ID; original ID is retained and full new fingerprint reapproved. |
| Existing name-only model | Repeat registration, setup and key replacement do not add an ID to the existing definition. |
| Native ID changed | Full fingerprint changes; approval cannot transfer silently. |

These are outgoing registration/approval contracts with a synthetic management
adapter. Native compilation and protected-listener enrollment are separate checks.
