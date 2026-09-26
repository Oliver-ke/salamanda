"""Step Functions task Lambdas: one issue, one MicroVM, always terminated.
The event never carries secrets; dispatch reads them and sends them straight to the worker."""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .microvm import http_json
from .selection import FAILED, QUEUED, RUNNING, TOO_BIG

MAX_POLLS = 120  # x 30 s = 60 minutes; must match the state machine's Choice
HEALTH_ATTEMPTS = 30


@dataclass
class TaskDeps:
    github: object
    microvms: object
    secrets: Callable[[], dict]
    image_arn: str
    max_duration_s: int
    http: Callable = field(default=http_json)
    sleep: Callable = field(default=time.sleep)


def start(event: dict, deps: TaskDeps) -> dict:
    deps.github.add_labels(event["issue"], [RUNNING])
    deps.github.remove_label(event["issue"], QUEUED)
    vm = deps.microvms.run(deps.image_arn, deps.max_duration_s)
    return {**event, **vm, "polls": 0}


def dispatch(event: dict, deps: TaskDeps) -> dict:
    vm = event["microvmId"]
    base = f"https://{deps.microvms.wait_running(vm)}"
    headers = deps.microvms.auth_headers(vm)
    for _ in range(HEALTH_ATTEMPTS):
        if deps.http("GET", f"{base}/health", headers)[0] == 200:
            break
        deps.sleep(2)
    else:
        raise RuntimeError("the worker never answered /health")
    job = {k: event[k] for k in ("repo", "issue", "sha")}
    status, body = deps.http("POST", f"{base}/jobs", headers, {**job, "secrets": deps.secrets()})
    if status != 202:
        raise RuntimeError(f"worker refused the job: HTTP {status} {body.get('error', '')}")
    return {**event, "endpoint": base.removeprefix("https://")}


def poll(event: dict, deps: TaskDeps) -> dict:
    vm = event["microvmId"]
    base = f"https://{event.get('endpoint') or deps.microvms.wait_running(vm)}"
    status, body = deps.http("GET", f"{base}/jobs/current", deps.microvms.auth_headers(vm))
    if status != 200:
        raise RuntimeError(f"worker status unavailable: HTTP {status}")
    return {**event, "polls": event.get("polls", 0) + 1, "state": body.get("state"),
            "result": body.get("result")}


def _why(event: dict) -> str:
    if "error" in event:
        err = event["error"] or {}
        return f"{err.get('Error', 'error')}: {str(err.get('Cause', ''))[:1500]}"
    if event.get("polls", 0) >= MAX_POLLS:
        return "timed out after 60 minutes"
    return "the worker ended without reporting a result"


def finish(event: dict, deps: TaskDeps) -> dict:
    # Terminate first: whatever happens next (GitHub down), the MicroVM is gone.
    if event.get("microvmId"):
        deps.microvms.terminate(event["microvmId"])
    issue, gh = event["issue"], deps.github
    outcome = (event.get("result") or {}).get("outcome") if event.get("state") == "done" else None
    gh.remove_label(issue, QUEUED)
    gh.remove_label(issue, RUNNING)
    if outcome == "gave_up":
        gh.add_labels(issue, [TOO_BIG])
    elif outcome != "pr_opened":
        gh.add_labels(issue, [FAILED])
        if outcome is None:  # the worker never reported, so it never commented
            gh.comment(issue, f"Agent run: **error**\n\n{_why(event)}\n\n"
                              "The MicroVM was terminated. Re-add `agent:ready` to retry.")
    return {"issue": issue, "outcome": outcome or "error"}


def _deps() -> TaskDeps:  # pragma: no cover - AWS wiring
    import boto3

    from .microvm import MicroVMs
    from .secrets import github_client, secret

    region = os.environ["AWS_REGION"]
    return TaskDeps(
        github=github_client(),
        microvms=MicroVMs(boto3.client("lambda-microvms", region_name=region), region),
        secrets=lambda: {"anthropic_api_key": secret(os.environ["ANTHROPIC_SECRET_ARN"]),
                         "github_app_private_key": secret(os.environ["GITHUB_KEY_SECRET_ARN"])},
        image_arn=os.environ["IMAGE_ARN"], max_duration_s=int(os.environ["MAX_RUN_SECONDS"]))


def start_handler(event, context):  # pragma: no cover - AWS wiring
    return start(event, _deps())


def dispatch_handler(event, context):  # pragma: no cover - AWS wiring
    return dispatch(event, _deps())


def poll_handler(event, context):  # pragma: no cover - AWS wiring
    return poll(event, _deps())


def finish_handler(event, context):  # pragma: no cover - AWS wiring
    return finish(event, _deps())
