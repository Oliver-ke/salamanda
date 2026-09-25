from loop_agent.sandbox import Workspace
from loop_agent.toolbox import Budget, Toolbox
from loop_agent.tools import make_tools

from .conftest import PROTECTED
from .fakes import FakeGitHub, ok


def test_make_tools_exposes_exactly_the_designed_tools(repo):
    tb = Toolbox(Workspace(repo, PROTECTED), Budget(10), FakeGitHub(), 7, lambda c: ok(c))
    names = [t.tool_name for t in make_tools(tb)]
    assert names == ["read_file", "write_file", "list_files", "search", "run",
                     "file_child_issue", "finish", "give_up"]
