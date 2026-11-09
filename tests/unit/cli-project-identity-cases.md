# A repo becomes a project with no setup

Spec 009 ST30 "A repo not set up in Keeplane" (D149, ADR 030). Journey: DEV-02,
DEV-03. Run `python -m pytest tests/unit/test_cli_project_identity.py`.

| Case | Expected result |
| --- | --- |
| PID-01 Fixed IDs | The project-ID namespace is `11b4916a-02a8-514d-b6ff-66bd26dee3af` and `git@github.com:Platform/Payments-API.git` is project `14f3b742-22cb-5def-ae55-3b92aa511552`. These never change: changing them would move every repo to a new project. |
| PID-02 One remote, many forms | SSH (`git@host:path`, `ssh://`, `git+ssh://`), HTTPS and HTTP, `git://`, user names and passwords, ports, double or trailing slashes, a `.git` ending and letter case all give the same project. |
| PID-03 Name | The name is the remote's path as written, without host, credentials or `.git`, such as `platform/payments-api`. |
| PID-04 Different remotes | Another host, another owner (a fork) or another repo name is another project. |
| PID-05 Local remotes | A folder path, `file://` URL, Windows drive path, empty path or unknown scheme gives no remote project, so the repo is treated as having no remote. |
| PID-06 Clones | Two clones of one remote, written differently, are one project, from any folder inside the repo. Nothing is written to the repo. |
| PID-07 Reading Git config | The first `url` of `[remote "origin"]` is used, with quotes, comments, the old `[remote.origin]` form, key case and continued lines read as Git reads them. Git is never run. A remote called `Origin` is a different remote. |
| PID-08 No remote | A random ID is saved once in `.git/keeplane/project` (file 0600, folder 0700) with the repo's top folder name, never its path, and reused after. Git shows nothing to commit. Adding an `origin` later moves the repo to the remote's project. A damaged saved file is refused and left as it is. |
| PID-09 Worktrees | A worktree has its main checkout's project, with or without a remote; with none, it shares the saved ID and the main folder's name. |
| PID-10 Submodules | A submodule is its own project from its own remote, or its own saved ID in its own Git folder. |
| PID-11 Not a repo | Outside a repo, or with a broken `.git` file, the developer is told to run inside a repo or pass `--project` and `--name`. |
| PID-12 Overrides and names | `--project` and `--name` override the repo (both together need no repo). A bad `--project` is refused. Names longer than 120 characters keep their end; control characters are dropped. |
