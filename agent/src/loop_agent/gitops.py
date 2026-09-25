"""Git, owned by the worker. The agent never runs git."""

import os
import re
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path

CREDENTIALS_IN_URL = re.compile(r"(https?://)[^/@\s]+@")
GIT_TIMEOUT_S = 300
# Agent-run commands execute agent-written code. Whatever they leave in the tree
# must never run as the worker: no hooks (post-commit, reference-transaction and
# pre-push all ignore --no-verify) and no fsmonitor command.
SAFE_CONFIG = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]


class GitError(Exception):
    pass


def redact(text: str) -> str:
    return CREDENTIALS_IN_URL.sub(r"\1***@", text)


class Git:
    def __init__(self, repo_dir: Path, author_name: str, author_email: str, timeout: int = GIT_TIMEOUT_S):
        self.repo_dir = repo_dir
        self.identity = ["-c", f"user.name={author_name}", "-c", f"user.email={author_email}"]
        self.timeout = timeout

    def _check_git_dir(self) -> None:
        """.git must be a real directory owned by the worker and writable by nobody
        else; otherwise its config (filters, insteadOf) is not the worker's."""
        git_dir = self.repo_dir / ".git"
        try:
            st = os.lstat(git_dir)
        except FileNotFoundError:
            raise GitError(f"{git_dir} does not exist") from None
        foreign_group_write = st.st_mode & 0o020 and st.st_gid != os.getegid()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
                or st.st_mode & 0o002 or foreign_group_write):
            raise GitError(f"{git_dir} must be a directory owned by the worker and not "
                           "writable by anyone else")

    def _git(self, *args: str, env: Mapping[str, str] | None = None) -> str:
        self._check_git_dir()
        try:
            proc = subprocess.run(["git", *SAFE_CONFIG, *self.identity, *args], cwd=self.repo_dir,
                                  capture_output=True, text=True, timeout=self.timeout,
                                  env={**os.environ, **env} if env else None)
        except subprocess.TimeoutExpired:
            raise GitError(redact(f"git {args[0]} timed out after {self.timeout}s"))
        if proc.returncode != 0:
            raise GitError(redact(f"git {args[0]} failed: {proc.stderr.strip()}"))
        return proc.stdout

    def prepare(self, sha: str, branch: str) -> None:
        self._git("fetch", "--no-tags", "origin", "main")
        self._git("checkout", "--force", "-B", branch, sha)
        self._git("reset", "--hard", sha)
        # -fd, not -fdx: keep ignored files, above all the snapshot's node_modules.
        self._git("clean", "-fd")

    def stage_all(self) -> list[str]:
        self._git("add", "-A")
        out = self._git("diff", "--cached", "--name-only", "-z", "--no-renames")
        return [p for p in out.split("\0") if p]

    def commit(self, message: str) -> str:
        self._git("commit", "--no-verify", "-m", message)
        return self._git("rev-parse", "HEAD").strip()

    def push(self, branch: str, url: str, env: Mapping[str, str] | None = None) -> None:
        """`env` carries the credential (GIT_CONFIG_* extraheader), so it never
        appears in argv, which every process in the container can read."""
        # --force: agent/* branches belong to the worker. main is protected server-side.
        self._git("push", "--force", url, f"HEAD:refs/heads/{branch}", env=env)
