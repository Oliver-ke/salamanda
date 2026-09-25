import pytest

from loop_agent.gitops import Git, GitError, redact

from .conftest import git


@pytest.fixture
def remote_and_clone(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-b", "main")
    (seed / ".gitignore").write_text("node_modules/\n")
    (seed / "a.txt").write_text("one\n")
    (seed / "old.txt").write_text("old\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-m", "base")
    sha = git(seed, "rev-parse", "HEAD").strip()
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "--bare", str(seed), str(remote))
    clone = tmp_path / "clone"
    git(tmp_path, "clone", str(remote), str(clone))
    return remote, clone, sha


def make(clone):
    return Git(clone, author_name="loop-sdlc[bot]", author_email="1+loop-sdlc[bot]@users.noreply.github.com")


def test_prepare_checks_out_sha_on_branch_and_cleans_but_keeps_ignored(remote_and_clone):
    _, clone, sha = remote_and_clone
    (clone / "stray.txt").write_text("leftover")
    (clone / "a.txt").write_text("dirty\n")
    (clone / "node_modules").mkdir()
    (clone / "node_modules" / "keep.js").write_text("")
    make(clone).prepare(sha, "agent/issue-7-add-form")
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == "agent/issue-7-add-form"
    assert git(clone, "rev-parse", "HEAD").strip() == sha
    assert not (clone / "stray.txt").exists()
    assert (clone / "a.txt").read_text() == "one\n"
    assert (clone / "node_modules" / "keep.js").exists()


def test_stage_all_reports_adds_and_deletes_without_rename_detection(remote_and_clone):
    _, clone, sha = remote_and_clone
    g = make(clone)
    g.prepare(sha, "agent/issue-7-x")
    (clone / "old.txt").rename(clone / "new.txt")
    assert sorted(g.stage_all()) == ["new.txt", "old.txt"]


def test_stage_all_empty_when_nothing_changed(remote_and_clone):
    _, clone, sha = remote_and_clone
    g = make(clone)
    g.prepare(sha, "agent/issue-7-x")
    assert g.stage_all() == []


def test_commit_uses_bot_identity_and_push_creates_branch(remote_and_clone):
    remote, clone, sha = remote_and_clone
    g = make(clone)
    g.prepare(sha, "agent/issue-7-x")
    (clone / "b.txt").write_text("b\n")
    g.stage_all()
    new_sha = g.commit("Add b (#7)")
    assert git(clone, "log", "-1", "--format=%an").strip() == "loop-sdlc[bot]"
    g.push("agent/issue-7-x", str(remote))
    assert git(remote, "rev-parse", "refs/heads/agent/issue-7-x").strip() == new_sha


def test_push_failure_redacts_credentials(remote_and_clone):
    _, clone, sha = remote_and_clone
    g = make(clone)
    g.prepare(sha, "agent/issue-7-x")
    with pytest.raises(GitError) as info:
        g.push("agent/issue-7-x", "https://x-access-token:ghs_SECRET123@127.0.0.1:9/o/r.git")
    # git may already hide the credentials itself; either way they must never appear.
    assert "ghs_SECRET123" not in str(info.value)


def test_redact():
    assert redact("fatal: https://x-access-token:abc@github.com/o/r.git") == \
        "fatal: https://***@github.com/o/r.git"
