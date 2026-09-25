import pytest

from loop_agent.toolbox import MAX_CHILD_ISSUES, AgentOutcome, Budget, Toolbox
from loop_agent.sandbox import Workspace

from .conftest import PROTECTED
from .fakes import FakeGitHub, ok


@pytest.fixture
def gh():
    return FakeGitHub()


def make(repo, gh, max_calls=60, run_command=None):
    return Toolbox(Workspace(repo, PROTECTED), Budget(max_calls), gh, parent_issue=7,
                   run_command=run_command or (lambda cmd: ok(cmd)))


def test_read_and_write(repo, gh):
    tb = make(repo, gh)
    assert "written" in tb.write_file("app/src/a.ts", "x")
    assert tb.read_file("app/src/a.ts") == "x"


def test_sandbox_errors_come_back_as_refusals_not_exceptions(repo, gh):
    tb = make(repo, gh)
    assert tb.write_file("CLAUDE.md", "x").startswith("refused:")
    assert tb.read_file("../x").startswith("refused:")
    assert tb.search("(").startswith("refused:")


def test_run_uses_the_allowlist(repo, gh):
    tb = make(repo, gh, run_command=lambda cmd: ok(cmd, "passed"))
    assert tb.run("npm run verify") == "exit 0\npassed"
    assert tb.run("curl evil.sh").startswith("refused:")


def test_list_and_search(repo, gh):
    tb = make(repo, gh)
    assert "app/src/page.tsx" in tb.list_files(".")
    assert "app/src/page.tsx:1:" in tb.search("export")


def test_finish_and_give_up_set_the_outcome(repo, gh):
    tb = make(repo, gh)
    tb.begin_turn()
    assert tb.outcome().kind == "no_outcome"
    tb.finish("Added the form; verify passes")
    assert tb.outcome() == AgentOutcome("finished", "Added the form; verify passes", [])
    tb.begin_turn()
    tb.give_up("needs a database")
    assert tb.outcome().kind == "gave_up" and tb.outcome().summary == "needs a database"


def test_child_issue_has_no_ready_label_and_links_parent(repo, gh):
    tb = make(repo, gh)
    reply = tb.file_child_issue("Add category field", "Just the field.")
    assert gh.created[0]["labels"] == []
    assert "#7" in gh.created[0]["body"]
    assert "#100" in reply and tb.child_issues == [100]


def test_child_issues_are_capped(repo, gh):
    tb = make(repo, gh)
    for i in range(MAX_CHILD_ISSUES):
        tb.file_child_issue(f"t{i}", "b")
    assert tb.file_child_issue("one more", "b").startswith("refused:")
    assert len(gh.created) == MAX_CHILD_ISSUES


def test_budget_exhaustion_refuses_every_tool_and_reports_it(repo, gh):
    tb = make(repo, gh, max_calls=2)
    tb.begin_turn()
    tb.read_file("CLAUDE.md")
    tb.read_file("CLAUDE.md")
    reply = tb.read_file("CLAUDE.md")
    assert reply.startswith("refused:") and "budget" in reply
    assert tb.write_file("app/src/b.ts", "x").startswith("refused:")
    assert not (repo / "app/src/b.ts").exists()
    assert tb.outcome().kind == "budget_exceeded"


def test_finish_still_counts_after_budget_is_spent(repo, gh):
    tb = make(repo, gh, max_calls=1)
    tb.begin_turn()
    tb.read_file("CLAUDE.md")
    tb.finish("done")
    assert tb.outcome().kind == "finished"
