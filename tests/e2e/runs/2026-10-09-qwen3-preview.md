# Qwen3 local preview — 9 October 2026

The optional native Qwen3 4B runner served `qwen3-4b-instruct` on host port
14424 with 12,288 active context tokens. Keeplane's app and gateway ran in
Docker; the protected admin preview ran on port 3001. The
[plain-English cases](../qwen3-local-cases.md) and
[machine result](2026-10-09-qwen3-local.json) passed **3/3**: admin discovery,
registration with Public approval, and a real answer through Keeplane and its
gateway. The model was left registered for local use.

The first [full regression attempt](2026-10-09-qwen3-regression.json) reported
26/28 suites. Both failures were in the regression manifest: the Docker and
kind runner scripts each returned five passing cases, including the existing
`LOCAL-24` context-readback case, while the manifest still expected four.
After adding that case ID, the
[corrected full run](2026-10-09-qwen3-regression-corrected.json) passed
**28/28 suites and 142/142 recorded cases**. No product case failed in the
first attempt or the corrected run.

After regression, the native runner returned healthy, the Qwen3 model still
appeared in Keeplane's model list, and the Docker and kind public previews
served successfully. The protected preview redirected unauthenticated visits
to sign-in as expected. The runner file and process log are outside Git; the
configuration, cases, executable checks and results are versioned here.
