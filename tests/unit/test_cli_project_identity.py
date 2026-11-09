"""A repo becomes a Keeplane project with no setup (Spec 009 ST30, ADR 030).

Cases: tests/unit/cli-project-identity-cases.md (PID-01 to PID-12).
"""

import json
import os
import shutil
import stat
import subprocess
import uuid

import pytest

from components.cli import project_identity
from components.cli.project_identity import ProjectIdentityError

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(
    GIT is None, reason="Git is needed to build sample repos"
)


def git(directory, *arguments):
    environment = dict(
        os.environ,
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_AUTHOR_NAME="Sample",
        GIT_AUTHOR_EMAIL="sample@example.test",
        GIT_COMMITTER_NAME="Sample",
        GIT_COMMITTER_EMAIL="sample@example.test",
    )
    return subprocess.run(
        [GIT, "-C", str(directory), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout


def repo(path, remote=None):
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    if remote:
        git(path, "remote", "add", "origin", remote)
    (path / "README.md").write_text("sample\n")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "Start")
    return path


def test_pid_01_namespace_and_a_known_repo_id_never_change():
    # Project IDs can't change after release: these values are pinned for good.
    assert str(project_identity.NAMESPACE) == "11b4916a-02a8-514d-b6ff-66bd26dee3af"
    assert project_identity.NAMESPACE == uuid.uuid5(
        uuid.NAMESPACE_URL, "keeplane:project-identity:v1"
    )
    project = project_identity.remote_project(
        "git@github.com:Platform/Payments-API.git"
    )
    assert project.id == "14f3b742-22cb-5def-ae55-3b92aa511552"
    assert project.name == "Platform/Payments-API"


SAME_REMOTE = [
    "https://github.com/Platform/Payments-API.git",
    "https://github.com/platform/payments-api",
    "https://github.com/platform/payments-api/",
    "https://github.com/platform/payments-api.git/",
    "https://developer:token-123@GitHub.com/platform/payments-api.git",
    "https://github.com:443/platform//payments-api.git",
    "http://github.com/platform/payments-api",
    "git@github.com:platform/payments-api.git",
    "github.com:platform/payments-api",
    "ssh://git@github.com/platform/payments-api.git",
    "ssh://git@github.com:2222/platform/payments-api",
    "git+ssh://git@github.com/platform/payments-api.git",
    "git://github.com/platform/payments-api.git",
    "  https://github.com/platform/payments-api.git  ",
]


@pytest.mark.parametrize("url", SAME_REMOTE)
def test_pid_02_every_form_of_one_remote_is_one_project(url):
    project = project_identity.remote_project(url)
    assert project.id == project_identity.remote_project(SAME_REMOTE[0]).id
    assert project.source == "remote"
    assert project.name.lower() == "platform/payments-api"
    assert "token" not in project.name and "github" not in project.name.lower()


@pytest.mark.parametrize(
    "url, name",
    [
        ("https://gitlab.example.test/group/sub/Tool.git", "group/sub/Tool"),
        ("git@gitlab.example.test:group/sub/tool", "group/sub/tool"),
        ("https://user:pass@host.test/one.git", "one"),
    ],
)
def test_pid_03_the_name_is_the_remote_path_without_host_credentials_or_ending(
    url, name
):
    assert project_identity.remote_project(url).name == name


def test_pid_04_different_hosts_or_paths_are_different_projects():
    ids = {
        project_identity.remote_project(url).id
        for url in (
            "https://github.com/platform/payments-api",
            "https://gitlab.com/platform/payments-api",
            "https://github.com/fork/payments-api",
            "https://github.com/platform/payments-api-v2",
        )
    }
    assert len(ids) == 4


@pytest.mark.parametrize(
    "url",
    [
        "/srv/git/sample.git",
        "../sample",
        "file:///srv/git/sample.git",
        "C:/repos/sample",
        "https://github.com/",
        "https://github.com/.git",
        "ftp://host/sample",
        "https://bad\nhost/x",
    ],
)
def test_pid_05_local_or_unusable_remotes_have_no_remote_project(url):
    assert project_identity.remote_project(url) is None


@needs_git
def test_pid_06_a_clone_uses_its_origin_remote(tmp_path):
    first = repo(tmp_path / "one", "git@github.com:platform/payments-api.git")
    second = repo(tmp_path / "two", "https://dev@github.com/Platform/payments-api")
    (first / "src").mkdir()
    a = project_identity.identify(first / "src")
    b = project_identity.identify(second)
    assert a.id == b.id and a.source == b.source == "remote"
    assert a.name == "platform/payments-api"  # The server keeps the first name it saw.
    assert not (first / ".git" / "keeplane").exists()
    assert git(first, "status", "--porcelain", "--untracked-files=no") == ""


def write_config(tmp_path, text):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / ".git" / "config").write_text(text)
    return tmp_path


@pytest.mark.parametrize(
    "text",
    [
        (
            '[remote "upstream"]\n\turl = https://other.test/x/y\n'
            '[remote "origin"]\n\turl = https://github.com/platform/payments-api.git\n'
        ),
        '[Remote "origin"]\n\tURL = "https://github.com/platform/payments-api.git" ; note\n',
        "[remote.origin]\n\turl=https://github.com/platform/payments-api # note\n",
        (
            '# comment\n[remote "origin"] url = https://github.com/platform/payments-api\n'
            "\turl = https://mirror.test/other/repo\n"
        ),
        '[remote "origin"]\n\turl = https://github.com/platform/\\\npayments-api\n',
    ],
)
def test_pid_07_git_config_is_read_as_git_reads_it_without_running_git(tmp_path, text):
    write_config(tmp_path, text)
    assert (
        project_identity.identify(tmp_path).id
        == project_identity.remote_project(
            "https://github.com/platform/payments-api"
        ).id
    )


def test_pid_07_a_differently_cased_remote_name_is_another_remote(tmp_path):
    write_config(tmp_path, '[remote "Origin"]\n\turl = https://github.com/a/b\n')
    assert project_identity.identify(tmp_path).source == "saved"


@needs_git
def test_pid_08_no_remote_saves_one_random_id_inside_the_git_folder(tmp_path):
    sample = repo(tmp_path / "Sample Repo")
    first = project_identity.identify(sample)
    saved = sample / ".git" / "keeplane" / "project"
    assert first.source == "saved" and first.name == "Sample Repo"
    assert str(tmp_path) not in first.name
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert stat.S_IMODE(saved.parent.stat().st_mode) == 0o700
    assert json.loads(saved.read_text()) == {
        "format": "keeplane-project-v1",
        "id": first.id,
        "name": "Sample Repo",
    }
    assert project_identity.identify(sample / ".") == first
    assert git(sample, "status", "--porcelain") == ""  # Never committed.
    assert [p.name for p in saved.parent.iterdir()] == ["project"]
    other = repo(tmp_path / "other")
    assert project_identity.identify(other).id != first.id


@needs_git
def test_pid_08_a_remote_added_later_takes_over(tmp_path):
    sample = repo(tmp_path / "sample")
    assert project_identity.identify(sample).source == "saved"
    git(sample, "remote", "add", "origin", "https://github.com/platform/payments-api")
    assert project_identity.identify(sample).source == "remote"


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        ('{"format": "keeplane-project-v1", "id": "nope", "name": "x"}'),
        "[]",
    ],
)
def test_pid_08_a_damaged_saved_id_is_refused_not_replaced(tmp_path, content):
    write_config(tmp_path, "")
    (tmp_path / ".git" / "keeplane").mkdir()
    (tmp_path / ".git" / "keeplane" / "project").write_text(content)
    with pytest.raises(ProjectIdentityError, match="can't read"):
        project_identity.identify(tmp_path)
    assert (tmp_path / ".git" / "keeplane" / "project").read_text() == content


@needs_git
@pytest.mark.parametrize("remote", [None, "https://github.com/platform/payments-api"])
def test_pid_09_worktrees_share_the_main_checkouts_project(tmp_path, remote):
    main = repo(tmp_path / "payments", remote)
    git(main, "worktree", "add", "-q", str(tmp_path / "feature"), "-b", "feature")
    feature = project_identity.identify(tmp_path / "feature")
    assert feature == project_identity.identify(main)
    if remote is None:
        assert feature.name == "payments"
        assert not (tmp_path / "feature" / "keeplane").exists()


@needs_git
def test_pid_10_a_submodule_is_its_own_project(tmp_path):
    library = repo(tmp_path / "library", "https://github.com/platform/shared-lib.git")
    app = repo(tmp_path / "app", "https://github.com/platform/app.git")
    git(
        app,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(library),
        "vendor/lib",
    )
    inside = project_identity.identify(app / "vendor" / "lib")
    assert (app / "vendor" / "lib" / ".git").is_file()
    # The submodule's own origin is the local library path, so it saves its own ID.
    assert inside.source == "saved" and inside.name == "lib"
    assert (
        app / ".git" / "modules" / "vendor" / "lib" / "keeplane" / "project"
    ).is_file()
    assert project_identity.identify(app).name == "platform/app"
    git(
        app / "vendor" / "lib",
        "remote",
        "set-url",
        "origin",
        "git@github.com:platform/shared-lib.git",
    )
    assert (
        project_identity.identify(app / "vendor" / "lib").name == "platform/shared-lib"
    )


def test_pid_11_outside_a_repo_the_developer_is_told_what_to_do(tmp_path):
    with pytest.raises(ProjectIdentityError) as error:
        project_identity.identify(tmp_path)
    assert str(error.value) == project_identity.NOT_A_REPO
    assert "--project and --name" in str(error.value)


@pytest.mark.parametrize("pointer", ["gitdir: missing", "nonsense", ""])
def test_pid_11_a_broken_git_file_is_refused(tmp_path, pointer):
    (tmp_path / ".git").write_text(pointer)
    with pytest.raises(ProjectIdentityError, match="can't read"):
        project_identity.identify(tmp_path)


def test_pid_12_given_flags_override_the_repo(tmp_path):
    write_config(tmp_path, '[remote "origin"]\n\turl = https://github.com/a/b\n')
    given = str(uuid.uuid4())
    assert project_identity.resolve(
        tmp_path, uuid.UUID(given).hex, "Mine"
    ) == project_identity.Project(given, "Mine", "given")
    assert project_identity.resolve(tmp_path, given).name == "a/b"
    assert (
        project_identity.resolve(tmp_path, None, "Mine").id
        == project_identity.remote_project("https://github.com/a/b").id
    )
    # Both flags need no repo at all.
    assert project_identity.resolve(tmp_path / "x", given, "Mine").id == given
    with pytest.raises(ProjectIdentityError, match="valid project UUID"):
        project_identity.resolve(tmp_path, "not-a-uuid", "Mine")


def test_pid_12_long_or_unprintable_names_fit_the_server_rule():
    name = project_identity.remote_project(
        "https://host.test/" + "/".join(["segment"] * 40) + "/end"
    ).name
    assert len(name) <= 120 and name.endswith("/end") and not name.startswith("/")
    assert project_identity.display_name("\x1b[31m") == "[31m"
    assert project_identity.display_name("\x00") == "Unnamed repo"
