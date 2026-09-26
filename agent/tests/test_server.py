import json
import threading
import urllib.error
import urllib.request

import pytest

from loop_agent.run import RunResult
from loop_agent.server import JobServer

SHA = "c" * 40


def post(port, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/jobs", data=json.dumps(payload).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def request(port, method, path, body=b""):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body or None, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as err:
        return err.code


@pytest.fixture
def server():
    release = threading.Event()
    done = []
    finished = threading.Event()

    def handle(job, secrets):
        release.wait(5)
        return RunResult("pr_opened", "https://x/pull/1", "ok")

    def on_done(job, result):
        done.append((job, result))
        finished.set()

    srv = JobServer(handle, on_done, expected_repo="o/r", host="127.0.0.1", port=0)
    srv.start()
    yield srv, release, done, finished
    release.set()
    srv.stop()


def test_accepts_a_job_and_reports_completion(server):
    srv, release, done, finished = server
    assert post(srv.port, {"repo": "o/r", "issue": 7, "sha": SHA}) == (202, {"accepted": True})
    release.set()
    assert finished.wait(5)
    assert done[0][0].issue == 7 and done[0][1].outcome == "pr_opened"


def test_busy_returns_409(server):
    srv, release, done, finished = server
    assert post(srv.port, {"repo": "o/r", "issue": 7, "sha": SHA})[0] == 202
    status, body = post(srv.port, {"repo": "o/r", "issue": 8, "sha": SHA})
    assert status == 409 and "busy" in body["error"]


@pytest.mark.parametrize("payload", [
    {"repo": "o/r", "issue": 7, "sha": "short"},
    {"repo": "o/r", "issue": 0, "sha": SHA},
    {"repo": "o/r", "issue": "7", "sha": SHA},
    {"repo": "o/r", "sha": SHA},
])
def test_invalid_job_returns_400(server, payload):
    srv, *_ = server
    assert post(srv.port, payload)[0] == 400


def test_wrong_repo_returns_400(server):
    srv, *_ = server
    status, body = post(srv.port, {"repo": "evil/repo", "issue": 7, "sha": SHA})
    assert status == 400 and "repo" in body["error"]


def test_health_and_404(server):
    srv, *_ = server
    with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/health", timeout=5) as resp:
        assert json.loads(resp.read()) == {"busy": False}
    with pytest.raises(urllib.error.HTTPError) as info:
        urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/nope", timeout=5)
    assert info.value.code == 404


def test_malformed_json_returns_400(server):
    srv, *_ = server
    req = urllib.request.Request(f"http://127.0.0.1:{srv.port}/jobs", data=b"{not json", method="POST")
    with pytest.raises(urllib.error.HTTPError) as info:
        urllib.request.urlopen(req, timeout=5)
    assert info.value.code == 400


def test_hook_paths_answer_any_method(server):
    srv, *_ = server
    for method in ("GET", "POST", "PUT"):
        assert request(srv.port, method, "/aws/lambda-microvms/runtime/v1/ready", b"{}" if method != "GET" else b"") == 200
    assert request(srv.port, "POST", "/aws/lambda-microvms/runtime/v1/validate", b"{}") == 200


def test_current_reports_idle_running_then_done_with_result(server):
    srv, release, done, finished = server
    assert get(srv.port, "/jobs/current") == (200, {"state": "idle", "result": None})
    post(srv.port, {"repo": "o/r", "issue": 7, "sha": SHA})
    assert get(srv.port, "/jobs/current")[1]["state"] == "running"
    release.set()
    assert finished.wait(5)
    status, body = get(srv.port, "/jobs/current")
    assert body["state"] == "done" and body["result"]["outcome"] == "pr_opened"


def test_secrets_reach_the_handler_but_never_the_status():
    seen = {}
    finished = threading.Event()

    def handle(job, secrets):
        seen.update(secrets)
        return RunResult("pr_opened", "https://x/pull/1", "ok")

    srv = JobServer(handle, lambda job, result: finished.set(), expected_repo="o/r",
                    host="127.0.0.1", port=0)
    srv.start()
    try:
        secrets = {"anthropic_api_key": "sk-ant-SECRET", "github_app_private_key": "PEM-SECRET"}
        assert post(srv.port, {"repo": "o/r", "issue": 7, "sha": SHA, "secrets": secrets})[0] == 202
        assert finished.wait(5)
        assert seen == secrets
        raw = json.dumps(get(srv.port, "/jobs/current")[1])
        assert "SECRET" not in raw
    finally:
        srv.stop()


@pytest.mark.parametrize("secrets", [
    {"aws_key": "x"}, {"anthropic_api_key": ""}, {"anthropic_api_key": 5}, ["anthropic_api_key"],
])
def test_bad_secrets_are_rejected(server, secrets):
    srv, *_ = server
    assert post(srv.port, {"repo": "o/r", "issue": 7, "sha": SHA, "secrets": secrets})[0] == 400


def test_once_refuses_a_second_job_but_keeps_answering_status():
    finished = threading.Event()
    srv = JobServer(lambda job, secrets: RunResult("pr_opened", "https://x/pull/1", "ok"),
                    lambda job, result: finished.set(), expected_repo="o/r",
                    host="127.0.0.1", port=0, once=True)
    srv.start()
    try:
        assert post(srv.port, {"repo": "o/r", "issue": 7, "sha": SHA})[0] == 202
        assert finished.wait(5)
        status, body = post(srv.port, {"repo": "o/r", "issue": 8, "sha": SHA})
        assert status == 409 and "already" in body["error"]
        assert get(srv.port, "/jobs/current")[1]["state"] == "done"
        assert srv._thread.is_alive()
    finally:
        srv.stop()


def test_without_once_a_finished_server_takes_another_job(server):
    srv, release, done, finished = server
    release.set()
    assert post(srv.port, {"repo": "o/r", "issue": 7, "sha": SHA})[0] == 202
    assert finished.wait(5)
    finished.clear()
    assert post(srv.port, {"repo": "o/r", "issue": 8, "sha": SHA})[0] == 202


def test_handler_exception_becomes_an_error_result():
    finished = threading.Event()

    def handle(job, secrets):
        raise RuntimeError("boom")

    srv = JobServer(handle, lambda job, result: finished.set(), expected_repo="o/r",
                    host="127.0.0.1", port=0)
    srv.start()
    try:
        post(srv.port, {"repo": "o/r", "issue": 7, "sha": SHA})
        assert finished.wait(5)
        result = get(srv.port, "/jobs/current")[1]["result"]
        assert result["outcome"] == "error" and "RuntimeError: boom" in result["detail"]
    finally:
        srv.stop()


def test_negative_or_huge_content_length_is_rejected(server):
    srv, *_ = server
    for length in ("-1", str(10 * 1024 * 1024)):
        req = urllib.request.Request(f"http://127.0.0.1:{srv.port}/jobs", data=b"{}", method="POST",
                                     headers={"content-length": length})
        with pytest.raises(urllib.error.HTTPError) as info:
            urllib.request.urlopen(req, timeout=5)
        assert info.value.code == 400
