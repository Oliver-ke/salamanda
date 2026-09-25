import hashlib
import shutil
import subprocess

import pytest

from loop_agent.checks import ensure_dependencies, run_pr_check

from .conftest import REPO_ROOT, git


def test_ensure_dependencies_skips_when_lockfile_matches_snapshot(tmp_path):
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "node_modules").mkdir()
    snap = tmp_path / "snap.sha256"
    snap.write_text(hashlib.sha256(b"{}").hexdigest() + "\n")

    def runner(*a, **k):
        raise AssertionError("npm ci must not run")

    assert ensure_dependencies(tmp_path, snap, runner=runner) is False


def test_ensure_dependencies_runs_npm_ci_when_lockfile_changed(tmp_path):
    (tmp_path / "package-lock.json").write_text('{"changed": true}')
    (tmp_path / "node_modules").mkdir()
    snap = tmp_path / "snap.sha256"
    snap.write_text("0" * 64)
    ran = []

    def runner(argv, **kwargs):
        ran.append((argv, kwargs["cwd"]))
        return subprocess.CompletedProcess(argv, 0)

    assert ensure_dependencies(tmp_path, snap, command_user="runner", runner=runner) is True
    assert ran[0][0][-2:] == ["npm", "ci"] and ran[0][0][0] == "setpriv"


def test_ensure_dependencies_runs_without_snapshot(tmp_path):
    (tmp_path / "package-lock.json").write_text("{}")
    ran = []
    ensure_dependencies(tmp_path, None,
                        runner=lambda argv, **k: ran.append(argv) or subprocess.CompletedProcess(argv, 0))
    assert ran == [["npm", "ci"]]


def test_ensure_dependencies_runs_as_the_command_user_with_their_home_and_a_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/root")
    (tmp_path / "package-lock.json").write_text("{}")
    seen = {}

    def runner(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0)

    ensure_dependencies(tmp_path, None, command_user="runner", runner=runner)
    assert seen["env"]["HOME"] == "/home/runner" and seen["timeout"] == 900


def test_ensure_dependencies_raises_on_failure_and_on_timeout(tmp_path):
    (tmp_path / "package-lock.json").write_text("{}")
    with pytest.raises(subprocess.CalledProcessError):
        ensure_dependencies(tmp_path, None, runner=lambda argv, **k: subprocess.CompletedProcess(argv, 1))

    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    with pytest.raises(subprocess.TimeoutExpired):
        ensure_dependencies(tmp_path, None, runner=slow)


def test_pr_check_times_out_as_exit_124(tmp_path, monkeypatch):
    root, base = _repo_with_harness(tmp_path)
    real_run = subprocess.run

    def run(argv, **kwargs):
        if argv[0] == "node":
            assert kwargs["timeout"] == 120
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return real_run(argv, **kwargs)

    monkeypatch.setattr("loop_agent.checks.subprocess.run", run)
    result = run_pr_check(root, base, "loop-sdlc[bot]", "Closes #7")
    assert result.exit_code == 124 and "timed out after 120s" in result.output


def _repo_with_harness(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    git(root, "init", "-b", "main")
    shutil.copytree(REPO_ROOT / "harness", root / "harness",
                    ignore=shutil.ignore_patterns("node_modules"))
    (root / "app").mkdir()
    (root / "app" / "page.tsx").write_text("x\n")
    git(root, "add", "-A")
    git(root, "commit", "-m", "base")
    return root, git(root, "rev-parse", "HEAD").strip()


def test_pr_check_passes_a_clean_change(tmp_path):
    root, base = _repo_with_harness(tmp_path)
    (root / "app" / "page.tsx").write_text("y\n")
    git(root, "commit", "-am", "change")
    result = run_pr_check(root, base, "loop-sdlc[bot]", "Closes #7")
    assert result.exit_code == 0, result.output


def test_pr_check_fails_a_protected_change_and_a_missing_link(tmp_path):
    root, base = _repo_with_harness(tmp_path)
    (root / ".github").mkdir()
    (root / ".github" / "x.yml").write_text("x")
    git(root, "add", "-A")
    git(root, "commit", "-m", "sneaky")
    result = run_pr_check(root, base, "loop-sdlc[bot]", "no link")
    assert result.exit_code != 0
    assert "[protected-path]" in result.output and "[issue-link]" in result.output


def test_pr_check_uses_the_base_harness_not_the_working_tree(tmp_path):
    root, base = _repo_with_harness(tmp_path)
    # A change that neuters the checker in the working tree must not neuter the check.
    (root / "harness" / "src" / "protected.mjs").write_text(
        "export const PROTECTED_PATHS = []; export function isProtectedPath() { return false; }\n")
    git(root, "commit", "-am", "neuter")
    result = run_pr_check(root, base, "loop-sdlc[bot]", "Closes #7")
    assert result.exit_code != 0 and "harness/src/protected.mjs is a protected path" in result.output
