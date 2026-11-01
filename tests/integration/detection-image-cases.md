# Detection image cases

Run with an image built from a detection target (task 005-03, Spec 005 ST20):

```sh
docker build -f components/control-plane/Dockerfile --target postgres-detection \
  -t keeplane-preview:postgres-detection-local .
KEEPLANE_RUNTIME_DETECTION_IMAGE=keeplane-preview:postgres-detection-local \
  .venv/bin/python -m pytest tests/integration/test_detection_image.py -m live -s
```

The **detection image** CI job builds `postgres-detection`, the target a
Kubernetes PostgreSQL install uses, and runs it. The probe prints the load
time, a short check's median time and the peak memory; it never prints
request text.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| DI-01 | Start the image as its own user with no network, a read-only root filesystem, no capabilities and a 1 GiB memory limit with no swap (the chart's smallest accepted limit), then load the bundled detector and check an invented email and a plain coding request 20 times. | The process runs as user 65532 with no `pip`; `KEEPLANE_PERSONAL_DATA_MODEL` is `en_core_web_lg` and the install setting is not set in the image; the detector notices are in `/usr/share/keeplane/licenses`; `/app`, `/usr/local/lib`, `/tmp` and the home folder are not writable. The model loads without the network in under 300 seconds (the readiness wait) and below 1 GiB peak memory; the email is held as personal data and the coding request passes as clean. |

Not covered here: a pod on a cluster, where the kubelet enforces the memory
limit and the readiness probe; the chart side is in
[the chart detection cases](chart-detection-cases.md).
