"""Repo-confined file access for the agent's tools.

Defence in depth: CI pr-rules and the GitHub App's permissions are the real
boundary. This layer stops the obvious mistakes early and keeps the agent out of
places the worker itself relies on (.git hooks run when the worker commits).
"""

# Deferred evaluation: Workspace defines a method named `list`, which would
# otherwise shadow the builtin `list` for every `-> list[str]` annotation
# written later in the class body (e.g. on `search`).
from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from .protected import is_protected

SKIP_DIRS = {".git", "node_modules", ".next", ".venv", "__pycache__", "coverage"}
FORBIDDEN_PARTS = {".git", "node_modules"}
MAX_READ_BYTES = 200_000
MAX_SEARCH_RESULTS = 200


class SandboxError(Exception):
    pass


class Workspace:
    def __init__(self, root: Path, protected: Sequence[str]):
        self.root = root.resolve()
        self.protected = list(protected)

    def resolve(self, rel: str) -> Path:
        if not rel or rel.startswith("/") or "\\" in rel or "\0" in rel:
            raise SandboxError(f"{rel!r} must be a relative path inside the repository")
        resolved = (self.root / rel).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise SandboxError(f"{rel!r} resolves outside the repository")
        parts = resolved.relative_to(self.root).parts
        for part in FORBIDDEN_PARTS & set(parts):
            raise SandboxError(f"{rel!r} is inside {part}/, which the agent may not touch")
        return resolved

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def read(self, rel: str) -> str:
        path = self.resolve(rel)
        if not path.is_file():
            raise SandboxError(f"{rel!r} is not a file")
        if path.stat().st_size > MAX_READ_BYTES:
            raise SandboxError(f"{rel!r} is too large to read ({path.stat().st_size} bytes)")
        return path.read_text(encoding="utf-8", errors="replace")

    def write(self, rel: str, content: str) -> None:
        path = self.resolve(rel)
        # Check both the requested path and where it really points: a symlink
        # in app/src/ must not be a way to write CLAUDE.md.
        for candidate in {rel, self._rel(path)}:
            if is_protected(candidate, self.protected):
                raise SandboxError(f"{candidate!r} is a protected path; the agent may not change it")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _walk(self, rel: str):
        base = self.resolve(rel) if rel not in ("", ".") else self.root
        for path in sorted(base.rglob("*")):
            parts = path.relative_to(self.root).parts
            if SKIP_DIRS & set(parts) or not path.is_file():
                continue
            # A symlinked file's own repo-relative path can look innocuous
            # (e.g. app/src/leak.txt) while its target escapes the repo or
            # reaches into .git/ or node_modules/. Route every candidate
            # through resolve() so list() and search() refuse it the same
            # way read() and write() do, instead of silently following it.
            rel_path = path.relative_to(self.root).as_posix()
            try:
                self.resolve(rel_path)
            except SandboxError:
                continue
            yield path

    def list(self, rel: str = ".") -> list[str]:
        return [self._rel(p) for p in self._walk(rel)]

    def search(self, pattern: str, rel: str = ".") -> list[str]:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise SandboxError(f"invalid regex {pattern!r}: {exc}") from exc
        hits: list[str] = []
        for path in self._walk(rel):
            if path.stat().st_size > MAX_READ_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append(f"{self._rel(path)}:{number}: {line.strip()}")
                    if len(hits) >= MAX_SEARCH_RESULTS:
                        return hits
        return hits
