# Qwen3 local runner in the protected Docker preview

The native Qwen3 4B runner is an optional model on the same computer as the
Docker preview. Its file stays outside Git. These checks leave the model
registered so an admin can try it in Keeplane afterward.

## Q3-01 — Discover the running model

Given the pinned Qwen3 runner is healthy on the host and the protected
Keeplane preview is running, when the admin enters
`http://host.docker.internal:14424` and chooses Find models, then Keeplane
lists `qwen3-4b-instruct` and shows 12,288 active context tokens.

## Q3-02 — Add and approve the model

Given the model is discovered, when the admin adds it with the Public data
class, then it appears in Models and routing as a local model approved for
Public. Keeplane must verify an answer through its gateway before saving it.

## Q3-03 — Ask through Keeplane

Given the approved model, when the admin sends a short prompt through the
protected local API, then a nonempty answer returns under that model ID.
This checks a real local model route; the coding CLI trial separately
checks a real file edit and its tool calls.
