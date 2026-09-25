import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "app" / "src").mkdir(parents=True)
    (root / "app" / "src" / "page.tsx").write_text("export default () => null;\n")
    (root / "CLAUDE.md").write_text("# Rules\n")
    (root / "harness").mkdir()
    (root / "harness" / "x.mjs").write_text("// protected\n")
    return root


PROTECTED = [".github/", "harness/", "CLAUDE.md", "app/vitest.config.*"]
