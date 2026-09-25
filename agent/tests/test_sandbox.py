import os

import pytest

from loop_agent.sandbox import SandboxError, Workspace

from .conftest import PROTECTED


@pytest.fixture
def ws(repo):
    return Workspace(repo, PROTECTED)


def test_reads_a_file(ws):
    assert ws.read("app/src/page.tsx").startswith("export default")


def test_write_creates_parent_directories(ws, repo):
    ws.write("app/src/lib/expenses.ts", "export const x = 1;\n")
    assert (repo / "app/src/lib/expenses.ts").read_text() == "export const x = 1;\n"


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.txt", "app/../../outside.txt", "", "a\\b", "a\0b"])
def test_refuses_paths_outside_the_repo(ws, bad):
    with pytest.raises(SandboxError):
        ws.write(bad, "x")
    with pytest.raises(SandboxError):
        ws.read(bad)


def test_refuses_symlink_escape(ws, repo, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    os.symlink(outside, repo / "app/src/link.txt")
    with pytest.raises(SandboxError, match="outside the repository"):
        ws.read("app/src/link.txt")
    with pytest.raises(SandboxError):
        ws.write("app/src/link.txt", "x")


def test_refuses_symlink_to_protected(ws, repo):
    os.symlink(repo / "CLAUDE.md", repo / "app/src/rules.md")
    with pytest.raises(SandboxError, match="protected"):
        ws.write("app/src/rules.md", "no rules")
    assert (repo / "CLAUDE.md").read_text() == "# Rules\n"


def test_refuses_protected_write_but_allows_protected_read(ws):
    with pytest.raises(SandboxError, match="protected"):
        ws.write("harness/x.mjs", "x")
    with pytest.raises(SandboxError, match="protected"):
        ws.write("app/vitest.config.ts", "x")
    assert ws.read("CLAUDE.md") == "# Rules\n"


def test_refuses_git_dir(ws, repo):
    (repo / ".git" / "hooks").mkdir(parents=True)
    with pytest.raises(SandboxError, match=r"\.git"):
        ws.write(".git/hooks/pre-commit", "#!/bin/sh\ncurl evil")
    with pytest.raises(SandboxError, match=r"\.git"):
        ws.read(".git/config")


def test_refuses_node_modules(ws):
    with pytest.raises(SandboxError, match="node_modules"):
        ws.write("node_modules/react/index.js", "x")


def test_list_skips_vendor_and_vcs_dirs(ws, repo):
    (repo / ".git").mkdir(exist_ok=True)
    (repo / ".git" / "HEAD").write_text("ref")
    (repo / "node_modules" / "x").mkdir(parents=True)
    (repo / "node_modules" / "x" / "i.js").write_text("")
    listed = ws.list(".")
    assert "app/src/page.tsx" in listed
    assert not any(p.startswith((".git/", "node_modules/")) for p in listed)


def test_search_returns_path_line_text(ws):
    assert ws.search("export default") == ["app/src/page.tsx:1: export default () => null;"]


def test_search_rejects_bad_regex(ws):
    with pytest.raises(SandboxError, match="regex"):
        ws.search("(")


def test_read_refuses_huge_files(ws, repo):
    (repo / "big.txt").write_text("x" * 300_000)
    with pytest.raises(SandboxError, match="too large"):
        ws.read("big.txt")
