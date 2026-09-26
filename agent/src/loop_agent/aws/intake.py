"""Intake Lambda: queue the next eligible issue — only when nothing is in flight."""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import backoff
from .selection import (FAILED, OUTCOME_LABELS, QUEUED, READY, REQUEUED, RUNNING, closed_issues,
                        depends_on, select_issue)

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
    if label == QUEUED and REQUEUED in issue.labels:
        # Requeue at most once: a job that never starts twice (Pipe or state machine
        # broken) must not bounce between ready and queued forever.
        gh.remove_label(issue.number, REQUEUED)
        gh.add_labels(issue.number, [FAILED])
        gh.comment(issue.number, "Agent run: **error**\n\nThis issue was queued twice without its run "
                                 "starting; not requeuing again. Check the dead-letter queue and the Step "
                                 "Functions executions, then re-add `agent:ready`.")
    elif label == QUEUED:
        gh.add_labels(issue.number, [READY, REQUEUED])
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
    for label in OUTCOME_LABELS:  # a retry starts clean
        if label in selection.issue.labels:
            gh.remove_label(number, label)
    deps.send({"repo": deps.repo, "issue": number, "sha": sha})
    return {"queued": number, "sha": sha, "reasons": reasons}


@dataclass
class TickDeps:
    intake: IntakeDeps
    load: Callable[[], str | None]
    save: Callable[[str], None]
    base_s: int
    sleep_s: int


def run_tick(event: dict | None, deps: TickDeps) -> dict:
    """One scheduled tick or wake-up. Backoff errors never block intake: an
    unreadable record counts as due, and a failed save is only logged."""
    now = deps.intake.now()
    woken = bool((event or {}).get("wake"))
    try:
        state = backoff.parse(deps.load())
    except Exception as exc:  # fail open: check rather than sleep
        print(f"backoff: read failed ({type(exc).__name__}); treating as due")
        state = None
    if not woken and not backoff.due(state, now):
        return {"skipped": True, "next_at": state.next_at.isoformat()}
    result = run_intake(deps.intake)
    work = result.get("queued") is not None
    new = backoff.reset(now, deps.base_s) if (work or woken) else backoff.grow(state, now, deps.base_s, deps.sleep_s)
    try:
        deps.save(backoff.dump(new))
    except Exception as exc:
        print(f"backoff: write failed ({type(exc).__name__})")
    return {**result, "woken": woken, "next_interval_s": new.interval_s}


def handler(event, context):  # pragma: no cover - AWS wiring
    import boto3

    from .secrets import github_client

    sfn, sqs, ssm = boto3.client("stepfunctions"), boto3.client("sqs"), boto3.client("ssm")
    machine, queue = os.environ["STATE_MACHINE_ARN"], os.environ["QUEUE_URL"]
    parameter = os.environ["BACKOFF_PARAMETER"]

    def running() -> int:
        return len(sfn.list_executions(stateMachineArn=machine, statusFilter="RUNNING",
                                       maxResults=10)["executions"])

    def send(message: dict) -> None:
        sqs.send_message(QueueUrl=queue, MessageBody=json.dumps(message), MessageGroupId=message["repo"],
                         MessageDeduplicationId=f"{message['issue']}-{message['sha']}")

    def load() -> str | None:
        return ssm.get_parameter(Name=parameter)["Parameter"]["Value"]

    def save(raw: str) -> None:
        ssm.put_parameter(Name=parameter, Value=raw, Type="String", Overwrite=True)

    # Build the GitHub client lazily: a skipped tick must not even read the secret.
    class LazyGitHub:
        _client = None

        def __getattr__(self, name):
            if LazyGitHub._client is None:
                LazyGitHub._client = github_client()
            return getattr(LazyGitHub._client, name)

    intake = IntakeDeps(LazyGitHub(), running, send, os.environ["LOOP_REPO"])
    result = run_tick(event, TickDeps(intake, load, save, int(os.environ["INTAKE_BASE_SECONDS"]),
                                      int(os.environ["INTAKE_SLEEP_SECONDS"])))
    print(json.dumps(result))
    return result
