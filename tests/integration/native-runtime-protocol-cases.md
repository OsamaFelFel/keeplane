# Streaming and tool-call authorization

This disposable trial keeps the current Django callback on the native chat path.
Synthetic providers return SSE text, a JSON tool call or streamed tool-call
fragments. The test compares the content and complete tool arguments after they
pass through the gateway. No tool is executed.

| Case | Expected result |
| --- | --- |
| SSE text | Text, event-stream content type, finish reason and terminal marker survive. |
| JSON tool call | Function name, call ID and arguments survive. |
| Streamed tool call | Argument fragments form the same complete call, followed by the terminal marker. |
| Allowed tool-result message | The synthetic provider receives the preceding assistant call, function arguments, matching call ID and result content, then returns an answer. |
| Approval withdrawn before the next request | The same valid stream or tool-result request is refused with no provider contact. |
| Provider credentials | Only the synthetic server-selected provider key arrives; developer, project and workload headers stay private. |
| Existing gateway | Its unrelated model and native configuration stay intact. |

Each protocol runs in managed and existing-gateway modes with real Django
records. Reports retain match booleans, not prompts, answers, arguments or keys.
Use the [native fixture prerequisites](native-runtime-authorization-cases.md),
then run from the repository with its Python test environment:

```sh
python -m pytest tests/integration/test_native_runtime_protocol.py -m live -q
```

The fixture removes its temporary containers, networks and databases on failure.
Generated reports stay outside Git. This proves bounded protocol transport and
fresh authorization before the next request. It does not prove actual tool
execution, token arrival timing, mid-stream revocation, cancellation, arbitrary
stream formats, broad fallback, TLS, Kubernetes or production policy wiring.
The release gateway remains open.
