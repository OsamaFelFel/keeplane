# Image requirement pin cases

Run `python -m pytest tests/unit/test_image_requirement_pins.py` (tasks 005-03
and 002-02). Optional package sets are installed into a prefix with
`--ignore-installed` and copied over each other, so two different pins of one
package in one image would leave two versions installed while the licence
inventories describe only one.

| ID | Plain-English action | Expected result |
| --- | --- | --- |
| IRP-01 | For every app Dockerfile target, collect the requirement files it installs, including its base stages and stages it copies from, and compare each package pinned in more than one of them. | Every shared package has one version, and the files that list hashes allow a common wheel. The PostgreSQL, CLI sign-in and detection target combines all four requirement files and shares `certifi` among others. |
| IRP-02 | Compare the packages listed in both the CLI sign-in and the detection licence inventories. | Each shared package has the same record in both (version, wheel, source and notices), and that wheel's hash is allowed by both requirement files. |
