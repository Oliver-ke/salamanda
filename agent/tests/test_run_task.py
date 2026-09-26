import io
import urllib.error
from dataclasses import dataclass, field

import pytest

from loop_agent.aws.microvm import http_json
from loop_agent.aws.run_task import MAX_POLLS, TaskDeps, dispatch, finish, poll, start

EVENT = {"repo": "o/r", "issue": 5, "sha": "c" * 40}
SECRETS = {"anthropic_api_key": "sk-ant-SECRET", "github_app_private_key": "PEM-SECRET"}


@dataclass
class Recorder:
    log: list = field(default_factory=list)
    fail_github: bool = False

    def add_labels(self, n, labels):
        self._gh(("add", n, tuple(labels)))

    def remove_label(self, n, label):
        self._gh(("remove", n, label))

    def comment(self, n, body):
        self._gh(("comment", n, body))

    def _gh(self, entry):
        if self.fail_github:
            raise RuntimeError("GitHub is down")
        self.log.append(entry)


class FakeVMs:
    def __init__(self, log):
        self.log = log

    def run(self, image_arn, max_duration_s):
        self.log.append(("run", image_arn, max_duration_s))
        return {"microvmId": "mvm-1"}

    def wait_running(self, microvm_id, timeout_s=120):
        return "mvm-1.lambda-microvm.eu-west-1.on.aws"

    def auth_headers(self, microvm_id):
        return {"X-aws-proxy-auth": "tok"}

    def terminate(self, microvm_id):
        self.log.append(("terminate", microvm_id))


def make(http=None, fail_github=False):
    rec = Recorder(fail_github=fail_github)
    calls = []

    def default_http(method, url, headers, body=None):
        calls.append((method, url, headers, body))
        if url.endswith("/health"):
            return 200, {"busy": False}
        if url.endswith("/jobs"):
            return 202, {"accepted": True}
        return 200, {"state": "running", "result": None}

    d = TaskDeps(rec, FakeVMs(rec.log), lambda: dict(SECRETS), "arn:image", 3900,
                 http=http or default_http, sleep=lambda s: None)
    return d, rec, calls


def test_start_swaps_labels_and_runs_a_microvm():
    d, rec, _ = make()
    out = start(dict(EVENT), d)
    assert out["microvmId"] == "mvm-1" and out["polls"] == 0
    assert ("add", 5, ("agent:running",)) in rec.log and ("remove", 5, "agent:queued") in rec.log
    assert ("run", "arn:image", 3900) in rec.log


def test_dispatch_waits_for_health_then_posts_job_with_secrets():
    attempts = []

    def http(method, url, headers, body=None):
        attempts.append((method, url, body))
        if url.endswith("/health"):
            return (0, {}) if len(attempts) < 3 else (200, {"busy": False})
        return 202, {"accepted": True}

    d, _, _ = make(http=http)
    out = dispatch({**EVENT, "microvmId": "mvm-1", "polls": 0}, d)
    method, url, body = attempts[-1]
    assert (method, url) == ("POST", "https://mvm-1.lambda-microvm.eu-west-1.on.aws/jobs")
    assert body == {**EVENT, "secrets": SECRETS}
    assert "secrets" not in out and "SECRET" not in str(out)


def test_dispatch_raises_when_worker_refuses_or_never_answers():
    d, _, _ = make(http=lambda m, u, h, b=None: (200, {}) if u.endswith("/health") else (409, {"error": "busy"}))
    with pytest.raises(RuntimeError, match="409"):
        dispatch({**EVENT, "microvmId": "mvm-1"}, d)
    d, _, _ = make(http=lambda m, u, h, b=None: (0, {}))
    with pytest.raises(RuntimeError, match="health"):
        dispatch({**EVENT, "microvmId": "mvm-1"}, d)


def test_poll_counts_and_reports_state():
    d, _, _ = make(http=lambda m, u, h, b=None: (200, {"state": "done", "result": {"outcome": "pr_opened"}}))
    out = poll({**EVENT, "microvmId": "mvm-1", "polls": 4}, d)
    assert out["polls"] == 5 and out["state"] == "done" and out["result"]["outcome"] == "pr_opened"


@pytest.mark.parametrize("outcome,label", [("gave_up", "agent:too-big"), ("verify_failed", "agent:failed"),
                                           ("guardrail_failed", "agent:failed")])
def test_finish_labels_by_outcome(outcome, label):
    d, rec, _ = make()
    finish({**EVENT, "microvmId": "mvm-1", "state": "done", "result": {"outcome": outcome}}, d)
    assert ("add", 5, (label,)) in rec.log
    assert not any(e[0] == "comment" for e in rec.log)  # the worker already commented


def test_finish_after_a_pr_only_clears_labels():
    d, rec, _ = make()
    out = finish({**EVENT, "microvmId": "mvm-1", "state": "done", "result": {"outcome": "pr_opened"}}, d)
    assert out["outcome"] == "pr_opened"
    assert not any(e[0] == "add" for e in rec.log)
    assert ("remove", 5, "agent:running") in rec.log


def test_finish_comment_carries_the_error_but_no_secret():
    d, rec, _ = make()
    err = {"Error": "RuntimeError", "Cause": "worker refused the job: HTTP 409 busy"}
    finish({**EVENT, "microvmId": "mvm-1", "error": err}, d)
    comment = next(e[2] for e in rec.log if e[0] == "comment")
    assert "RuntimeError" in comment and "409" in comment and "SECRET" not in comment
    assert ("add", 5, ("agent:failed",)) in rec.log


def test_finish_reports_a_timeout():
    d, rec, _ = make()
    finish({**EVENT, "microvmId": "mvm-1", "polls": MAX_POLLS, "state": "running"}, d)
    assert any(e[0] == "comment" and "timed out" in e[2] for e in rec.log)


def test_finish_before_a_microvm_existed_terminates_nothing():
    d, rec, _ = make()
    finish({**EVENT, "error": {"Error": "X", "Cause": "start failed"}}, d)
    assert not any(e[0] == "terminate" for e in rec.log)


def test_finish_terminates_before_any_github_call():
    d, rec, _ = make(fail_github=True)
    with pytest.raises(RuntimeError, match="GitHub is down"):
        finish({**EVENT, "microvmId": "mvm-1", "state": "done", "result": {"outcome": "pr_opened"}}, d)
    assert rec.log == [("terminate", "mvm-1")]


class FakeResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_json_ok_error_and_network_failure():
    assert http_json("GET", "https://x/h", {}, opener=lambda req, timeout: FakeResp(b'{"a": 1}')) == (200, {"a": 1})

    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 409, "Conflict", {}, io.BytesIO(b'{"error": "busy"}'))
    assert http_json("POST", "https://x/jobs", {}, {"k": 1}, opener=refuse) == (409, {"error": "busy"})

    def down(req, timeout):
        raise urllib.error.URLError("refused")
    assert http_json("GET", "https://x/h", {}, opener=down) == (0, {})
