"""Strands tool wrappers. Docstrings are what the model sees; logic lives in Toolbox."""

from strands import tool

from .toolbox import Toolbox


def make_tools(tb: Toolbox) -> list:
    @tool
    def read_file(path: str) -> str:
        """Read a text file. path is relative to the repository root."""
        return tb.read_file(path)

    @tool
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a text file with the full new content. path is relative
        to the repository root. Protected paths are refused."""
        return tb.write_file(path, content)

    @tool
    def list_files(path: str = ".") -> str:
        """List files under a directory (relative to the repository root), recursively."""
        return tb.list_files(path)

    @tool
    def search(pattern: str, path: str = ".") -> str:
        """Search file contents with a Python regex. Returns path:line: text matches."""
        return tb.search(pattern, path)

    @tool
    def run(command: str) -> str:
        """Run one allowed command: npm run verify|test|typecheck|lint|build, or
        npm run test --workspace app -- src/<path>.test.ts(x). Returns exit code and output."""
        return tb.run(command)

    @tool
    def file_child_issue(title: str, body: str) -> str:
        """File a smaller follow-up issue when this one is too big. A human approves it later."""
        return tb.file_child_issue(title, body)

    @tool
    def finish(summary: str) -> str:
        """Call once the issue is fully done and npm run verify passes. summary: one line
        saying what changed and how you verified it."""
        return tb.finish(summary)

    @tool
    def give_up(reason: str) -> str:
        """Call when you cannot finish honestly (too big, needs a protected file or a new
        dependency). reason: why."""
        return tb.give_up(reason)

    return [read_file, write_file, list_files, search, run, file_child_issue, finish, give_up]
