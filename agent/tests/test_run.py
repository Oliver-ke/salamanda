from dataclasses import dataclass, field

import pytest

from loop_agent.github import Issue
from loop_agent.run import Deps, Job, run_job
from loop_agent.toolbox import AgentOutcome

from .fakes import FakeGitHub, failed, ok

SHA = "a" * 40
ISSUE = Issue(7, "Add expense form", "amount + category", ["agent:ready"])


@dataclass
class FakeGit:
    changed: list = field(default_factory=lambda: ["app/src/form.tsx"])
    calls: list = field(default_factory=list)

    def prepare(self, sha, branch):
        self.calls.append(("prepare", sha, branch))

    def stage_all(self):
        self.calls.append(("stage_all",))
        return self.changed

    def commit(self, message):
        self.calls.append(("commit", message))
        return "b" * 40


class ScriptedAgent:
    """Returns the scripted outcomes in order, one per send()."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.prompts = []

    def session(self, toolbox):
        return self

    def send(self, prompt):
        self.prompts.append(prompt)
        return self.outcomes.pop(0)


def make_deps(agent, verify_results=(ok(),), check=ok("pr-check", "no violations"), gh=None, git=None):
    verify_iter = iter(verify_results)
    pushed = []
    deps = Deps(
        github=gh or FakeGitHub(issues={7: ISSUE}),
        git=git or FakeGit(),
        push=pushed.append,
        ensure_deps=lambda: None,
        make_toolbox=lambda issue: object(),
        agent=agent,
        verify=lambda: next(verify_iter),
        pr_check=lambda base, body: check,
        max_verify_retries=2,
    )
    return deps, pushed


FINISHED = AgentOutcome("finished", "Added the form; verify passes")


def test_happy_path_opens_one_pr_that_closes_the_issue():
    deps, pushed = make_deps(ScriptedAgent(FINISHED))
    result = run_job(Job("o/r", 7, SHA), deps)
    assert result.outcome == "pr_opened" and result.pr_url.endswith("/pull/50")
    assert deps.git.calls[0] == ("prepare", SHA, "agent/issue-7-add-expense-form")
    assert pushed == ["agent/issue-7-add-expense-form"]
    pr = deps.github.prs[0]
    assert pr["head"] == "agent/issue-7-add-expense-form" and pr["base"] == "main"
    assert pr["body"].startswith("Closes #7\n")
    assert deps.github.comments == [(7, "Opened https://github.com/o/r/pull/50")]


def test_verify_failure_is_sent_back_to_the_agent_then_succeeds():
    agent = ScriptedAgent(FINISHED, FINISHED)
    deps, pushed = make_deps(agent, verify_results=(failed(output="expected 3 got 2"), ok()))
    assert run_job(Job("o/r", 7, SHA), deps).outcome == "pr_opened"
    assert "expected 3 got 2" in agent.prompts[1]


def test_verify_failing_after_retries_opens_no_pr_and_pushes_wip_only_if_guardrail_passes():
    agent = ScriptedAgent(FINISHED, FINISHED, FINISHED)
    deps, pushed = make_deps(agent, verify_results=(failed(), failed(), failed(output="still red")))
    result = run_job(Job("o/r", 7, SHA), deps)
    assert result.outcome == "verify_failed"
    assert deps.github.prs == []
    assert pushed == ["agent/issue-7-add-expense-form"]
    assert "still red" in deps.github.comments[-1][1]
    assert "agent/issue-7-add-expense-form" in deps.github.comments[-1][1]


def test_verify_failing_with_guardrail_violation_pushes_nothing():
    agent = ScriptedAgent(FINISHED, FINISHED, FINISHED)
    deps, pushed = make_deps(agent, verify_results=(failed(),) * 3,
                             check=failed("pr-check", "[protected-path] CLAUDE.md"))
    assert run_job(Job("o/r", 7, SHA), deps).outcome == "verify_failed"
    assert pushed == [] and deps.github.prs == []


def test_give_up_comments_children_and_opens_nothing():
    deps, pushed = make_deps(ScriptedAgent(AgentOutcome("gave_up", "too big", [101, 102])))
    result = run_job(Job("o/r", 7, SHA), deps)
    assert result.outcome == "gave_up" and result.child_issues == [101, 102]
    assert pushed == [] and deps.github.prs == []
    body = deps.github.comments[0][1]
    assert "too big" in body and "#101" in body and "#102" in body


@pytest.mark.parametrize("kind", ["no_outcome", "budget_exceeded"])
def test_agent_stopping_without_finishing_is_an_error_with_no_pr(kind):
    deps, pushed = make_deps(ScriptedAgent(AgentOutcome(kind)))
    result = run_job(Job("o/r", 7, SHA), deps)
    assert result.outcome == "error" and kind in result.detail
    assert pushed == [] and deps.github.prs == []


def test_no_changes_opens_no_pr():
    deps, pushed = make_deps(ScriptedAgent(FINISHED), git=FakeGit(changed=[]))
    assert run_job(Job("o/r", 7, SHA), deps).outcome == "no_changes"
    assert pushed == [] and deps.github.prs == []


def test_guardrail_failure_pushes_nothing_and_reports_output():
    deps, pushed = make_deps(ScriptedAgent(FINISHED),
                             check=failed("pr-check", "[protected-path] .github/x.yml"))
    result = run_job(Job("o/r", 7, SHA), deps)
    assert result.outcome == "guardrail_failed"
    assert pushed == [] and deps.github.prs == []
    assert ".github/x.yml" in deps.github.comments[-1][1]


def test_unexpected_exception_becomes_error_and_is_reported():
    gh = FakeGitHub(issues={})
    deps, _ = make_deps(ScriptedAgent(), gh=gh)
    result = run_job(Job("o/r", 7, SHA), deps)
    assert result.outcome == "error" and "KeyError" in result.detail
    assert gh.comments and gh.comments[0][0] == 7


def test_failure_to_comment_on_the_error_path_does_not_raise():
    gh = FakeGitHub(issues={}, fail_comment=True)
    deps, _ = make_deps(ScriptedAgent(), gh=gh)
    assert run_job(Job("o/r", 7, SHA), deps).outcome == "error"
