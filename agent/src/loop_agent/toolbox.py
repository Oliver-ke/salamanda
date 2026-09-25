"""What the agent's tools do, as plain methods. tools.py only wraps these for Strands.

Every tool returns a string. Refusals are returned, not raised, so the model reads
why and can recover — except that once the budget is spent every tool refuses,
while finish/give_up still record an outcome."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from .commands import CommandRejected, CommandResult, parse_allowed
from .sandbox import SandboxError, Workspace

MAX_CHILD_ISSUES = 5


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, max_tool_calls: int):
        self.max_tool_calls = max_tool_calls
        self.calls = 0
        self.exhausted = False

    def spend(self) -> None:
        self.calls += 1
        if self.calls > self.max_tool_calls:
            self.exhausted = True
            raise BudgetExceeded(
                f"tool-call budget of {self.max_tool_calls} is spent; call finish or give_up now")


@dataclass
class AgentOutcome:
    kind: str  # finished | gave_up | no_outcome | budget_exceeded
    summary: str = ""
    child_issues: list[int] = field(default_factory=list)


class IssueCreator(Protocol):
    def create_issue(self, title: str, body: str, labels: list[str]) -> int: ...


class Toolbox:
    def __init__(self, workspace: Workspace, budget: Budget, issues: IssueCreator,
                 parent_issue: int, run_command: Callable[[str], CommandResult]):
        self.workspace = workspace
        self.budget = budget
        self.issues = issues
        self.parent_issue = parent_issue
        self.run_command = run_command
        self.child_issues: list[int] = []
        self._kind = "no_outcome"
        self._summary = ""

    def begin_turn(self) -> None:
        self._kind, self._summary = "no_outcome", ""

    def outcome(self) -> AgentOutcome:
        kind = self._kind
        if kind == "no_outcome" and self.budget.exhausted:
            kind = "budget_exceeded"
        return AgentOutcome(kind, self._summary, list(self.child_issues))

    def _guarded(self, action: Callable[[], str]) -> str:
        try:
            self.budget.spend()
            return action()
        except (SandboxError, CommandRejected, BudgetExceeded) as exc:
            return f"refused: {exc}"

    def read_file(self, path: str) -> str:
        return self._guarded(lambda: self.workspace.read(path))

    def write_file(self, path: str, content: str) -> str:
        def action():
            self.workspace.write(path, content)
            return f"written: {path} ({len(content)} chars)"
        return self._guarded(action)

    def list_files(self, path: str = ".") -> str:
        return self._guarded(lambda: "\n".join(self.workspace.list(path)) or "(no files)")

    def search(self, pattern: str, path: str = ".") -> str:
        return self._guarded(lambda: "\n".join(self.workspace.search(pattern, path)) or "(no matches)")

    def run(self, command: str) -> str:
        def action():
            # Toolbox itself is the allowlist boundary: parse_allowed raises
            # CommandRejected for anything outside it, regardless of what the
            # injected run_command would otherwise happily execute.
            parse_allowed(command)
            result = self.run_command(command)
            return f"exit {result.exit_code}\n{result.output}"
        return self._guarded(action)

    def file_child_issue(self, title: str, body: str) -> str:
        def action():
            if len(self.child_issues) >= MAX_CHILD_ISSUES:
                raise SandboxError(f"at most {MAX_CHILD_ISSUES} child issues per run")
            number = self.issues.create_issue(
                title, f"{body}\n\nSplit from #{self.parent_issue} by the loop agent.", labels=[])
            self.child_issues.append(number)
            return f"filed #{number}"
        return self._guarded(action)

    def finish(self, summary: str) -> str:
        self._kind, self._summary = "finished", summary
        return "recorded: finished. Stop now."

    def give_up(self, reason: str) -> str:
        self._kind, self._summary = "gave_up", reason
        return "recorded: gave up. Stop now."
