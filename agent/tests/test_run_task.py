import io
import urllib.error
from dataclasses import dataclass, field

import pytest

from loop_agent.aws.microvm import MicroVMs, http_json
from loop_agent.aws.run_task import MAX_POLLS, TaskDeps, dispatch, finish, poll, start

EVENT = {"repo": "o/r", "issue": 5, "sha": "c" * 40, "execution": "exec-1"}
JOB = {"repo": EVENT["repo"], "issue": EVENT["issue"], "sha": EVENT["sha"]}
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

    def run(self, image_arn, max_duration_s, client_token):
        self.log.append(("run", image_arn, max_duration_s, client_token))
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

    def default_http(method, url, headers, body=None, timeout=30):
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
    assert ("remove", 5, "agent:ready") in rec.log  # a hand-started run must not stay ready
    assert ("run", "arn:image", 3900, "exec-1") in rec.log


def test_dispatch_waits_for_health_then_posts_job_with_secrets():
    attempts = []

    def http(method, url, headers, body=None, timeout=30):
        attempts.append((method, url, body))
        if url.endswith("/health"):
            return (0, {}) if len(attempts) < 3 else (200, {"busy": False})
        return 202, {"accepted": True}

    d, _, _ = make(http=http)
    out = dispatch({**EVENT, "microvmId": "mvm-1", "polls": 0}, d)
    method, url, body = attempts[-1]
    assert (method, url) == ("POST", "https://mvm-1.lambda-microvm.eu-west-1.on.aws/jobs")
    assert body == {**JOB, "secrets": SECRETS}
    assert "secrets" not in out and "SECRET" not in str(out)


def test_dispatch_raises_when_worker_refuses_or_never_answers():
    d, _, _ = make(http=lambda m, u, h, b=None, timeout=30: (200, {}) if u.endswith("/health")
                    else (409, {"error": "busy"}))
    with pytest.raises(RuntimeError, match="409"):
        dispatch({**EVENT, "microvmId": "mvm-1"}, d)
    d, _, _ = make(http=lambda m, u, h, b=None, timeout=30: (0, {}))
    with pytest.raises(RuntimeError, match="health"):
        dispatch({**EVENT, "microvmId": "mvm-1"}, d)


def test_poll_counts_and_reports_state():
    d, _, _ = make(http=lambda m, u, h, b=None, timeout=30: (200, {"state": "done",
                                                                    "result": {"outcome": "pr_opened"}}))
    out = poll({**EVENT, "microvmId": "mvm-1", "polls": 4}, d)
    assert out["polls"] == 5 and out["state"] == "done" and out["result"]["outcome"] == "pr_opened"


@pytest.mark.parametrize("outcome,label", [("gave_up", "agent:too-big"), ("verify_failed", "agent:failed"),
                                           ("guardrail_failed", "agent:failed")])
def test_finish_labels_by_outcome(outcome, label):
    d, rec, _ = make()
    finish({**EVENT, "microvmId": "mvm-1", "state": "done",
            "result": {"outcome": outcome, "detail": "d", "commented": True}}, d)
    assert ("add", 5, (label,)) in rec.log
    assert not any(e[0] == "comment" for e in rec.log)  # the worker already commented


def test_finish_after_a_pr_only_clears_labels():
    d, rec, _ = make()
    out = finish({**EVENT, "microvmId": "mvm-1", "state": "done", "result": {"outcome": "pr_opened"}}, d)
    assert out["outcome"] == "pr_opened"
    assert not any(e[0] == "add" for e in rec.log)
    assert ("remove", 5, "agent:running") in rec.log


def test_finish_removes_requeued_with_the_other_claim_labels():
    d, rec, _ = make()
    finish({**EVENT, "microvmId": "mvm-1", "state": "done", "result": {"outcome": "pr_opened"}}, d)
    for label in ("agent:queued", "agent:running", "agent:requeued"):
        assert ("remove", 5, label) in rec.log


def test_finish_explains_a_worker_error_the_worker_could_not_comment_on():
    d, rec, _ = make()
    result = {"outcome": "error", "pr_url": None, "detail": "configuration: LOOP_BOT_LOGIN must end in [bot]",
              "child_issues": [], "commented": False}
    finish({**EVENT, "microvmId": "mvm-1", "state": "done", "result": result}, d)
    comments = [e[2] for e in rec.log if e[0] == "comment"]
    assert len(comments) == 1
    assert "Agent run: **error**" in comments[0] and "configuration:" in comments[0]
    assert "Re-add `agent:ready` to retry" in comments[0]
    assert ("add", 5, ("agent:failed",)) in rec.log


def test_finish_adds_no_comment_when_the_worker_already_commented():
    d, rec, _ = make()
    result = {"outcome": "verify_failed", "pr_url": None, "detail": "still red", "child_issues": [],
              "commented": True}
    finish({**EVENT, "microvmId": "mvm-1", "state": "done", "result": result}, d)
    assert not any(e[0] == "comment" for e in rec.log)


def test_finish_comment_truncates_a_long_worker_detail():
    d, rec, _ = make()
    result = {"outcome": "error", "detail": "x" * 5000, "commented": False}
    finish({**EVENT, "microvmId": "mvm-1", "state": "done", "result": result}, d)
    comment = next(e[2] for e in rec.log if e[0] == "comment")
    assert "x" * 1500 in comment and "x" * 1501 not in comment


def test_finish_without_a_detail_falls_back_to_why():
    d, rec, _ = make()
    finish({**EVENT, "microvmId": "mvm-1", "state": "done", "result": {"outcome": "error"}}, d)
    comment = next(e[2] for e in rec.log if e[0] == "comment")
    assert "the worker ended without reporting a result" in comment


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


class FakeMicrovmsClient:
    class exceptions:
        class ResourceNotFoundException(Exception):
            pass

        class ConflictException(Exception):
            pass

    def __init__(self, states=None, terminate_raises=None):
        self.states = list(states or [])
        self.run_calls = []
        self.terminate_calls = []
        self.terminate_raises = terminate_raises

    def run_microvm(self, **kwargs):
        self.run_calls.append(kwargs)
        return {"microvmId": "mvm-9"}

    def get_microvm(self, microvmIdentifier):
        return self.states.pop(0)

    def create_microvm_auth_token(self, **kwargs):
        return {"authToken": {"X-aws-proxy-auth": "tok"}}

    def terminate_microvm(self, microvmIdentifier):
        self.terminate_calls.append(microvmIdentifier)
        if self.terminate_raises:
            raise self.terminate_raises


def test_microvms_run_passes_no_execution_role_and_region_scoped_connectors():
    client = FakeMicrovmsClient()
    vms = MicroVMs(client, "eu-west-1")
    out = vms.run("arn:image", 3900, "exec-1")
    assert out == {"microvmId": "mvm-9"}
    kwargs = client.run_calls[0]
    assert "executionRoleArn" not in kwargs
    assert kwargs["clientToken"] == "exec-1"
    assert "eu-west-1" in kwargs["ingressNetworkConnectors"][0]
    assert "eu-west-1" in kwargs["egressNetworkConnectors"][0]


def test_microvms_wait_running_returns_endpoint_without_scheme_or_trailing_slash():
    client = FakeMicrovmsClient(states=[{"state": "RUNNING",
                                         "endpoint": "https://mvm-1.lambda-microvm.eu-west-1.on.aws/"}])
    vms = MicroVMs(client, "eu-west-1", sleep=lambda s: None)
    assert vms.wait_running("mvm-1") == "mvm-1.lambda-microvm.eu-west-1.on.aws"


@pytest.mark.parametrize("state", ["TERMINATED", "TERMINATING"])
def test_microvms_wait_running_raises_on_terminal_states(state):
    client = FakeMicrovmsClient(states=[{"state": state, "endpoint": "x", "stateReason": "boom"}])
    vms = MicroVMs(client, "eu-west-1", sleep=lambda s: None)
    with pytest.raises(RuntimeError, match=state):
        vms.wait_running("mvm-1")


def test_microvms_wait_running_raises_at_the_deadline():
    states = [{"state": "PENDING", "endpoint": "x"}, {"state": "PENDING", "endpoint": "x"}]
    client = FakeMicrovmsClient(states=states)
    clock = iter([0, 1, 200])  # deadline check, then an in-loop check that jumps past it
    vms = MicroVMs(client, "eu-west-1", sleep=lambda s: None, clock=lambda: next(clock))
    with pytest.raises(RuntimeError, match="PENDING"):
        vms.wait_running("mvm-1")


@pytest.mark.parametrize("exc_type", [FakeMicrovmsClient.exceptions.ResourceNotFoundException,
                                       FakeMicrovmsClient.exceptions.ConflictException])
def test_microvms_terminate_swallows_expected_exceptions(exc_type):
    client = FakeMicrovmsClient(terminate_raises=exc_type("gone"))
    vms = MicroVMs(client, "eu-west-1")
    vms.terminate("mvm-1")  # must not raise
    assert client.terminate_calls == ["mvm-1"]


def test_microvms_auth_headers_returns_a_dict():
    client = FakeMicrovmsClient()
    vms = MicroVMs(client, "eu-west-1")
    headers = vms.auth_headers("mvm-1")
    assert headers == {"X-aws-proxy-auth": "tok"}
    assert isinstance(headers, dict)


def test_http_json_ok_error_and_network_failure():
    assert http_json("GET", "https://x/h", {}, opener=lambda req, timeout: FakeResp(b'{"a": 1}')) == (200, {"a": 1})

    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 409, "Conflict", {}, io.BytesIO(b'{"error": "busy"}'))
    assert http_json("POST", "https://x/jobs", {}, {"k": 1}, opener=refuse) == (409, {"error": "busy"})

    def down(req, timeout):
        raise urllib.error.URLError("refused")
    assert http_json("GET", "https://x/h", {}, opener=down) == (0, {})


def test_finish_comment_drops_the_lambda_stack_trace():
    import json as _json
    d, rec, _ = make()
    cause = _json.dumps({"errorMessage": "not authorized to perform: lambda:PassNetworkConnector",
                         "errorType": "AccessDeniedException",
                         "stackTrace": ['  File "/var/task/loop_agent/aws/run_task.py", line 35, in start\n']})
    finish({**EVENT, "error": {"Error": "AccessDeniedException", "Cause": cause}}, d)
    comment = next(e[2] for e in rec.log if e[0] == "comment")
    assert "AccessDeniedException: not authorized to perform: lambda:PassNetworkConnector" in comment
    assert "stackTrace" not in comment and "/var/task" not in comment


def test_finish_keeps_a_non_json_cause_as_is():
    d, rec, _ = make()
    finish({**EVENT, "error": {"Error": "States.Timeout", "Cause": "Task timed out after 420 s"}}, d)
    comment = next(e[2] for e in rec.log if e[0] == "comment")
    assert "States.Timeout: Task timed out after 420 s" in comment


def test_finish_comment_redacts_credentials_in_urls():
    d, rec, _ = make()
    detail = "GitError: git push failed: fatal: https://x-access-token:ghs_SECRET@github.com/o/r.git"
    finish({**EVENT, "microvmId": "mvm-1", "state": "done",
            "result": {"outcome": "error", "detail": detail, "commented": False}}, d)
    comment = next(e[2] for e in rec.log if e[0] == "comment")
    assert "ghs_SECRET" not in comment and "https://***@github.com" in comment


def test_start_clears_the_requeue_marker():
    d, rec, _ = make()
    start(dict(EVENT), d)
    assert ("remove", 5, "agent:requeued") in rec.log
