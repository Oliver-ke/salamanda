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


def test_timeout_becomes_git_error(remote_and_clone, monkeypatch):
    import subprocess
    _, clone, sha = remote_and_clone
    g = Git(clone, author_name="loop-sdlc[bot]", author_email="1+loop-sdlc[bot]@users.noreply.github.com", timeout=1)

    def mock_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(["git", "fetch"], 1)

    monkeypatch.setattr("loop_agent.gitops.subprocess.run", mock_run)
    with pytest.raises(GitError) as info:
        g.prepare(sha, "agent/issue-7-x")
    assert "timed out" in str(info.value)


def _plant_hook(clone, name, marker):
    hook = clone / ".git" / "hooks" / name
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)


def test_hooks_never_run_when_the_worker_commits_or_pushes(remote_and_clone, tmp_path):
    remote, clone, sha = remote_and_clone
    g = make(clone)
    g.prepare(sha, "agent/issue-7-x")
    markers = {name: tmp_path / f"{name}.ran" for name in
               ("post-commit", "pre-push", "reference-transaction", "post-checkout")}
    for name, marker in markers.items():
        _plant_hook(clone, name, marker)
    (clone / "b.txt").write_text("b\n")
    g.stage_all()
    g.commit("Add b (#7)")
    g.push("agent/issue-7-x", str(remote))
    assert [name for name, marker in markers.items() if marker.exists()] == []


def test_fsmonitor_from_repo_config_never_runs(remote_and_clone, tmp_path):
    _, clone, sha = remote_and_clone
    g = make(clone)
    g.prepare(sha, "agent/issue-7-x")
    marker = tmp_path / "fsmonitor.ran"
    git(clone, "config", "core.fsmonitor", f"touch {marker}; false")
    (clone / "b.txt").write_text("b\n")
    g.stage_all()
    assert not marker.exists()


def test_push_with_credential_in_env_reaches_a_file_remote(remote_and_clone):
    remote, clone, sha = remote_and_clone
    g = make(clone)
    g.prepare(sha, "agent/issue-7-x")
    (clone / "b.txt").write_text("b\n")
    g.stage_all()
    new_sha = g.commit("Add b (#7)")
    g.push("agent/issue-7-x", str(remote), env={
        "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic ZmFrZQ=="})
    assert git(remote, "rev-parse", "refs/heads/agent/issue-7-x").strip() == new_sha


def test_push_credential_never_appears_in_argv(remote_and_clone, monkeypatch):
    import subprocess
    _, clone, _ = remote_and_clone
    seen = []

    def fake_run(argv, **kwargs):
        seen.append((argv, kwargs.get("env") or {}))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("loop_agent.gitops.subprocess.run", fake_run)
    make(clone).push("agent/issue-7-x", "https://github.com/o/r.git",
                     env={"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                          "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic ghs_SECRET"})
    (argv, env), = seen
    assert not any("ghs_SECRET" in a for a in argv)
    assert "ghs_SECRET" in env["GIT_CONFIG_VALUE_0"]


def test_worker_git_refuses_a_git_dir_others_can_write(remote_and_clone):
    _, clone, sha = remote_and_clone
    (clone / ".git").chmod(0o777)
    with pytest.raises(GitError, match="writable"):
        make(clone).prepare(sha, "agent/issue-7-x")
