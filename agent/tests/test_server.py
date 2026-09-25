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


@pytest.fixture
def server():
    release = threading.Event()
    done = []
    finished = threading.Event()

    def handle(job):
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
