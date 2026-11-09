# Repos as projects on the real server

Spec 009 ST30 "A repo not set up in Keeplane" (D149, ADR 030). Journey: DEV-03.
The CLI's own code calls the real Django runtime routes over HTTP. Run
`python -m pytest tests/integration/test_cli_repo_projects.py`.

| Case | Expected result |
| --- | --- |
| RPJ-01 Two developers, one remote | Two accounts in their own clones of one remote (one SSH, one HTTPS with a user name and other letter case) register one project. The Projects page shows it once, not set up, named `platform/payments-api`, with both developers. |
| RPJ-02 Every model until a class is set | With data classes on and no class set, the repo's project lists every approved model. Once an admin sets the class, only models approved for it are listed. |
| RPJ-03 No remote | A repo with no remote registers under its folder name, never its path, and keeps the same ID next time. |
