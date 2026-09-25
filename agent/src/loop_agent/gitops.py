"""Git, owned by the worker. The agent never runs git."""

import re
import subprocess
from pathlib import Path

CREDENTIALS_IN_URL = re.compile(r"(https?://)[^/@\s]+@")


class GitError(Exception):
    pass


def redact(text: str) -> str:
    return CREDENTIALS_IN_URL.sub(r"\1***@", text)


class Git:
    def __init__(self, repo_dir: Path, author_name: str, author_email: str):
        self.repo_dir = repo_dir
        self.identity = ["-c", f"user.name={author_name}", "-c", f"user.email={author_email}"]

    def _git(self, *args: str) -> str:
        proc = subprocess.run(["git", *self.identity, *args], cwd=self.repo_dir,
                              capture_output=True, text=True)
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

    def push(self, branch: str, url: str) -> None:
        # --force: agent/* branches belong to the worker; a retried issue
        # replaces its previous attempt. main is protected server-side.
        self._git("push", "--force", url, f"HEAD:refs/heads/{branch}")
