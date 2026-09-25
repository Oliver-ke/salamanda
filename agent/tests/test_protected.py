import json
import subprocess

import pytest

from loop_agent.protected import is_protected, load_protected_paths

from .conftest import REPO_ROOT

CASES = [
    ".github/workflows/ci.yml", "infra/main.tf", "harness/src/pr-rules.mjs",
    "agent/prompt.md", "CLAUDE.md", "./CLAUDE.md", "app/CLAUDE.md",
    "app/vitest.config.ts", "app/vitest.config.mts", "app/vitest.config.d/x.ts",
    "app/tsconfig.json", "app/tsconfig.base.json", "app/src/lib/x.ts",
    "app/src/harness-notes.md", "tasks/0001-x.md", "package.json", "app/package.json",
]


def test_load_protected_paths_reads_the_harness_list():
    entries = load_protected_paths(REPO_ROOT)
    assert "agent/" in entries and "harness/" in entries


@pytest.mark.parametrize("path,expected", [
    ("harness/x.mjs", True),
    ("app/vitest.config.ts", True),
    ("app/vitest.config.d/x.ts", False),
    ("app/src/page.tsx", False),
    ("./CLAUDE.md", True),
])
def test_is_protected_small_list(path, expected):
    assert is_protected(path, ["harness/", "CLAUDE.md", "app/vitest.config.*"]) is expected


def test_parity_with_the_javascript_matcher():
    """The Python matcher must agree with harness isProtectedPath on every case."""
    script = (
        "import { isProtectedPath } from './harness/src/protected.mjs';"
        f"console.log(JSON.stringify({json.dumps(CASES)}.map(isProtectedPath)));"
    )
    out = subprocess.run(["node", "--input-type=module", "-e", script], cwd=REPO_ROOT,
                         check=True, capture_output=True, text=True).stdout
    expected = json.loads(out)
    entries = load_protected_paths(REPO_ROOT)
    assert [is_protected(p, entries) for p in CASES] == expected
