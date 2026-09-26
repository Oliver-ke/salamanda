"""Intake Lambda: queue the next eligible issue — only when nothing is in flight."""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .selection import FAILED, QUEUED, READY, RUNNING, closed_issues, depends_on, select_issue

STALE_AFTER = timedelta(minutes=30)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class IntakeDeps:
    github: object
    running_executions: Callable[[], int]
    send: Callable[[dict], None]
    repo: str
    now: Callable[[], datetime] = field(default=_utcnow)


def _age(updated_at: str, now: datetime) -> timedelta:
    if not updated_at:
        return timedelta(0)  # unknown age: never treat as stale
    return now - datetime.fromisoformat(updated_at.replace("Z", "+00:00"))


def _reclaim(gh, issue, label: str) -> None:
    gh.remove_label(issue.number, label)
    if label == QUEUED:
        gh.add_labels(issue.number, [READY])
        gh.comment(issue.number, "Requeued: this issue was queued but its run never started (stale claim).")
    else:
        gh.add_labels(issue.number, [FAILED])
        gh.comment(issue.number, "Agent run: **error**\n\nThe run ended without cleaning up. "
                                 "Re-add `agent:ready` to retry.")


def run_intake(deps: IntakeDeps) -> dict:
    gh = deps.github
    running = deps.running_executions()
    in_flight = []
    for label in (QUEUED, RUNNING):
        for issue in gh.list_issues(label):
            if running == 0 and _age(issue.updated_at, deps.now()) > STALE_AFTER:
                _reclaim(gh, issue, label)
            else:
                in_flight.append(issue.number)
    if running or in_flight:
        return {"queued": None, "reason": "a run is already in flight", "in_flight": in_flight}

    candidates = gh.list_issues(READY)
    needed = sorted({dep for issue in candidates for dep in depends_on(issue.body)})
    dep_states = {dep: gh.issue_state(dep) for dep in needed}
    claimed = set().union(*(closed_issues(body) for _, body in gh.list_open_pull_requests()))
    selection = select_issue(candidates, dep_states, claimed)
    reasons = {str(n): why for n, why in selection.reasons.items()}
    if selection.issue is None:
        return {"queued": None, "reasons": reasons}

    number = selection.issue.number
    sha = gh.branch_sha("main")
    gh.add_labels(number, [QUEUED])
    gh.remove_label(number, READY)
    deps.send({"repo": deps.repo, "issue": number, "sha": sha})
    return {"queued": number, "sha": sha, "reasons": reasons}


def handler(event, context):  # pragma: no cover - AWS wiring
    import boto3

    from .secrets import github_client

    sfn, sqs = boto3.client("stepfunctions"), boto3.client("sqs")
    machine, queue = os.environ["STATE_MACHINE_ARN"], os.environ["QUEUE_URL"]

    def running() -> int:
        return len(sfn.list_executions(stateMachineArn=machine, statusFilter="RUNNING",
                                       maxResults=10)["executions"])

    def send(message: dict) -> None:
        sqs.send_message(QueueUrl=queue, MessageBody=json.dumps(message), MessageGroupId=message["repo"],
                         MessageDeduplicationId=f"{message['issue']}-{message['sha']}")

    result = run_intake(IntakeDeps(github_client(), running, send, os.environ["LOOP_REPO"]))
    print(json.dumps(result))
    return result
