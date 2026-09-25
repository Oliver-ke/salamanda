import hashlib
import shutil
import subprocess

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
