import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

from .commands import CommandResult, as_user, child_env


def ensure_dependencies(repo_dir: Path, snapshot_hash_file: Path | None,
                        command_user: str | None = None, runner=subprocess.run) -> bool:
    """Run `npm ci` only when the lockfile differs from the image snapshot's."""
    current = hashlib.sha256((repo_dir / "package-lock.json").read_bytes()).hexdigest()
    if (snapshot_hash_file is not None and snapshot_hash_file.exists()
            and snapshot_hash_file.read_text().strip() == current
            and (repo_dir / "node_modules").is_dir()):
        return False
    runner(as_user(["npm", "ci"], command_user), cwd=repo_dir, check=True,
           env=child_env(os.environ))
    return True


def run_pr_check(repo_dir: Path, base_sha: str, author: str, body: str) -> CommandResult:
    """The same guardrail CI runs, from the BASE commit's harness — never the
    working tree's, which the change under test could have rewritten."""
    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.run(["git", "archive", base_sha, "harness"], cwd=repo_dir,
                                 capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", tmp], input=archive.stdout, check=True)
        proc = subprocess.run(
            ["node", f"{tmp}/harness/src/cli/check-pr.mjs", "--base", base_sha, "--author", author],
            cwd=repo_dir, capture_output=True, text=True, env={**os.environ, "PR_BODY": body})
    return CommandResult("pr-check", proc.returncode, proc.stdout + proc.stderr)
