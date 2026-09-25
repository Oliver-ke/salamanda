import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

from .commands import CommandResult, as_user, child_env, grouped_run

NPM_CI_TIMEOUT_S = 900
PR_CHECK_TIMEOUT_S = 120


def ensure_dependencies(repo_dir: Path, snapshot_hash_file: Path | None,
                        command_user: str | None = None, runner=grouped_run) -> bool:
    """Run `npm ci` only when the lockfile differs from the image snapshot's."""
    current = hashlib.sha256((repo_dir / "package-lock.json").read_bytes()).hexdigest()
    if (snapshot_hash_file is not None and snapshot_hash_file.exists()
            and snapshot_hash_file.read_text().strip() == current
            and (repo_dir / "node_modules").is_dir()):
        return False
    argv = as_user(["npm", "ci"], command_user)
    # A timeout raises subprocess.TimeoutExpired; the job reports it as an error.
    proc = runner(argv, cwd=repo_dir, timeout=NPM_CI_TIMEOUT_S,
                  env=child_env(os.environ, command_user))
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, argv,
                                            output=(proc.stdout or "")[-4000:])
    return True


def run_pr_check(repo_dir: Path, base_sha: str, author: str, body: str) -> CommandResult:
    """The same guardrail CI runs, from the BASE commit's harness — never the
    working tree's, which the change under test could have rewritten."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.run(["git", "archive", base_sha, "harness"], cwd=repo_dir,
                                 capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", tmp], input=archive.stdout, check=True)
        try:
            proc = subprocess.run(
                ["node", f"{tmp}/harness/src/cli/check-pr.mjs", "--base", base_sha, "--author", author],
                cwd=repo_dir, capture_output=True, text=True, timeout=PR_CHECK_TIMEOUT_S,
                env={**os.environ, "PR_BODY": body})
        except subprocess.TimeoutExpired:
            return CommandResult("pr-check", 124, f"timed out after {PR_CHECK_TIMEOUT_S}s")
    return CommandResult("pr-check", proc.returncode, proc.stdout + proc.stderr)
