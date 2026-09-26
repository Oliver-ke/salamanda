"""Which issue the loop does next: the issue-backed successor to harness select.mjs."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from ..github import Issue
from ..prompts import JS_SPACE

READY, QUEUED, RUNNING = "agent:ready", "agent:queued", "agent:running"
FAILED, TOO_BIG = "agent:failed", "agent:too-big"
BLOCKING_LABELS = (QUEUED, RUNNING, FAILED, TOO_BIG)
PRIORITY = {"priority:high": 0, "priority:low": 2}
DEPENDS = re.compile(r"^depends on:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE)
# GitHub's closing keywords, mirrored from harness/src/pr-claim.mjs with ASCII/whitespace
# reconciliation: a closing keyword, then whitespace, then an issue reference (#N,
# owner/repo#N, or https?://github.com/.../issues/N), capturing the issue number.
CLOSING = re.compile(
    rf"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?{JS_SPACE}+"
    r"(?:#|[\w.-]+/[\w.-]+#|https?://github\.com/[\w.-]+/[\w.-]+/issues/)(\d+)\b",
    re.IGNORECASE | re.ASCII)


def depends_on(body: str) -> list[int]:
    match = DEPENDS.search(body or "")
    if not match:
        return []
    return sorted({int(n) for n in re.findall(r"#(\d+)", match.group(1))})


def closed_issues(body: str) -> set[int]:
    return {int(n) for n in CLOSING.findall(body or "")}


def priority(issue: Issue) -> int:
    return min((PRIORITY[label] for label in issue.labels if label in PRIORITY), default=1)


@dataclass
class Selection:
    issue: Issue | None
    reasons: dict[int, str] = field(default_factory=dict)


def select_issue(candidates: Iterable[Issue], dep_states: Mapping[int, str | None],
                 claimed: set[int]) -> Selection:
    reasons, eligible = {}, []
    for issue in candidates:
        reason = _ineligible(issue, dep_states, claimed)
        if reason:
            reasons[issue.number] = reason
        else:
            eligible.append(issue)
    eligible.sort(key=lambda i: (priority(i), i.number))
    return Selection(eligible[0] if eligible else None, reasons)


def _ineligible(issue: Issue, dep_states: Mapping[int, str | None], claimed: set[int]) -> str | None:
    if READY not in issue.labels:
        return "not approved (no agent:ready label)"
    for label in BLOCKING_LABELS:
        if label in issue.labels:
            return f"labelled {label}"
    if issue.number in claimed:
        return "claimed by an open pull request"
    for dep in depends_on(issue.body):
        if dep == issue.number:
            return "depends on itself"
        state = dep_states.get(dep)
        if state is None:
            return f"depends on unknown issue #{dep}"
        if state != "closed":
            return f"dependency #{dep} is still open"
    return None
