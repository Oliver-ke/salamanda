"""One job: one issue in, at most one pull request out. A failure never opens a PR."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .commands import CommandResult
from .gitops import redact
from .prompts import fix_prompt, pr_body, slugify, task_prompt
from .toolbox import AgentOutcome, Toolbox

OUTPUT_IN_COMMENT = 3000


@dataclass(frozen=True)
class Job:
    repo: str
    issue: int
    sha: str


@dataclass
class RunResult:
    outcome: str  # pr_opened | gave_up | verify_failed | guardrail_failed | no_changes | error
    pr_url: str | None
    detail: str
    child_issues: list[int] = field(default_factory=list)
    commented: bool = False  # True once this result was posted to the issue


class AgentSession(Protocol):
    def send(self, prompt: str) -> AgentOutcome: ...


class AgentRunner(Protocol):
    def session(self, toolbox: Toolbox) -> AgentSession: ...


@dataclass
class Deps:
    github: Any
    git: Any
    push: Callable[[str], None]
    ensure_deps: Callable[[], None]
    make_toolbox: Callable[[int], Toolbox]
    agent: AgentRunner
    verify: Callable[[], CommandResult]
    pr_check: Callable[[str, str], CommandResult]
    max_verify_retries: int = 2


def _tail(text: str) -> str:
    return text[-OUTPUT_IN_COMMENT:]


def _report(deps: Deps, issue: int, outcome: str, detail: str, children=()) -> RunResult:
    deps.github.comment(issue, f"Agent run: **{outcome}**\n\n{detail}")
    return RunResult(outcome, None, detail, list(children), commented=True)


def run_job(job: Job, deps: Deps) -> RunResult:
    try:
        return _run(job, deps)
    except Exception as exc:  # report, never crash the server
        detail = redact(f"{type(exc).__name__}: {exc}")
        try:
            deps.github.comment(job.issue, f"Agent run: **error**\n\n{detail}")
        except Exception:
            return RunResult("error", None, detail)
        return RunResult("error", None, detail, commented=True)


def _run(job: Job, deps: Deps) -> RunResult:
    issue = deps.github.get_issue(job.issue)
    # Per attempt: a retry must never force-push over the branch of an earlier,
    # possibly still open, pull request.
    branch = f"agent/issue-{issue.number}-{slugify(issue.title)}-{job.sha[:7]}"
    deps.git.prepare(job.sha, branch)
    deps.ensure_deps()
    session = deps.agent.session(deps.make_toolbox(issue.number))

    outcome = session.send(task_prompt(issue))
    retries = 0
    while True:
        if outcome.kind == "gave_up":
            children = ", ".join(f"#{n}" for n in outcome.child_issues) or "none"
            return _report(deps, issue.number, "gave_up",
                           f"{outcome.summary}\n\nChild issues filed: {children}", outcome.child_issues)
        if outcome.kind != "finished":
            return _report(deps, issue.number, "error",
                           f"the agent stopped without finishing ({outcome.kind})")
        verify = deps.verify()
        if verify.exit_code == 0:
            break
        if retries >= deps.max_verify_retries:
            return _verify_failed(job, deps, issue, branch, outcome, verify)
        retries += 1
        outcome = session.send(fix_prompt(verify))

    if not deps.git.stage_all():
        return _report(deps, issue.number, "no_changes", "the agent finished without changing any file")
    body = pr_body(issue, outcome.summary)
    deps.git.commit(f"{issue.title} (#{issue.number})")
    check = deps.pr_check(job.sha, body)
    if check.exit_code != 0:
        return _report(deps, issue.number, "guardrail_failed",
                       f"The guardrail check failed; nothing was pushed.\n\n```\n{_tail(check.output)}\n```")
    deps.push(branch)
    pr = deps.github.open_pull_request(head=branch, base="main", title=issue.title, body=body)
    deps.github.comment(issue.number, f"Opened {pr.url}")
    return RunResult("pr_opened", pr.url, outcome.summary, outcome.child_issues, commented=True)


def _verify_failed(job, deps, issue, branch, outcome, verify) -> RunResult:
    note = "No branch was pushed."
    if deps.git.stage_all():
        deps.git.commit(f"WIP: {issue.title} (#{issue.number}) — verify failing")
        if deps.pr_check(job.sha, pr_body(issue, outcome.summary)).exit_code == 0:
            deps.push(branch)
            note = f"Work in progress pushed to `{branch}` for inspection."
    return _report(deps, issue.number, "verify_failed",
                   f"`npm run verify` still fails after {deps.max_verify_retries} retries. "
                   f"{note}\n\n```\n{_tail(verify.output)}\n```")
