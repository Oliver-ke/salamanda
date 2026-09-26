import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from loop_agent.github import GitHubAppClient, GitHubError


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return pem, key.public_key()


def client(keypair, handler, now=1_000_000.0):
    pem, _ = keypair
    return GitHubAppClient("o/r", "123", pem, "456",
                           http=httpx.Client(transport=httpx.MockTransport(handler)),
                           clock=lambda: now)


def token_response():
    return httpx.Response(201, json={"token": "ghs_abc", "expires_at": "2099-01-01T00:00:00Z"})


def test_exchanges_an_app_jwt_for_an_installation_token_once(keypair):
    calls = []
    _, public = keypair

    def handler(req):
        calls.append(req)
        if req.url.path == "/app/installations/456/access_tokens":
            claims = jwt.decode(req.headers["authorization"].split()[1], public,
                                algorithms=["RS256"], options={"verify_exp": False})
            assert claims["iss"] == "123"
            return token_response()
        assert req.headers["authorization"] == "Bearer ghs_abc"
        return httpx.Response(200, json={"number": 7, "title": "T", "body": None,
                                         "labels": [{"name": "agent:ready"}]})

    c = client(keypair, handler)
    c.get_issue(7)
    c.get_issue(7)
    assert [r.url.path for r in calls].count("/app/installations/456/access_tokens") == 1


def test_get_issue_parses_and_rejects_pull_requests(keypair):
    def handler(req):
        if req.url.path.endswith("access_tokens"):
            return token_response()
        if req.url.path.endswith("/7"):
            return httpx.Response(200, json={"number": 7, "title": "Add form", "body": None,
                                             "labels": [{"name": "agent:ready"}]})
        return httpx.Response(200, json={"number": 8, "title": "x", "body": "",
                                         "labels": [], "pull_request": {}})

    c = client(keypair, handler)
    issue = c.get_issue(7)
    assert (issue.number, issue.title, issue.body, issue.labels) == (7, "Add form", "", ["agent:ready"])
    with pytest.raises(GitHubError, match="pull request"):
        c.get_issue(8)


def test_create_issue_comment_and_pull_request(keypair):
    seen = []

    def handler(req):
        if req.url.path.endswith("access_tokens"):
            return token_response()
        seen.append((req.method, req.url.path, json.loads(req.content or b"{}")))
        if req.url.path == "/repos/o/r/issues":
            return httpx.Response(201, json={"number": 101})
        if req.url.path == "/repos/o/r/pulls":
            return httpx.Response(201, json={"number": 50, "html_url": "https://github.com/o/r/pull/50"})
        return httpx.Response(201, json={})

    c = client(keypair, handler)
    assert c.create_issue("Child", "body", labels=[]) == 101
    c.comment(7, "hello")
    pr = c.open_pull_request("agent/issue-7-x", "main", "Add form", "Closes #7")
    assert (pr.number, pr.url) == (50, "https://github.com/o/r/pull/50")
    assert seen[0] == ("POST", "/repos/o/r/issues", {"title": "Child", "body": "body", "labels": []})
    assert seen[1] == ("POST", "/repos/o/r/issues/7/comments", {"body": "hello"})
    assert seen[2][2] == {"head": "agent/issue-7-x", "base": "main", "title": "Add form", "body": "Closes #7"}


def test_error_status_raises_with_status(keypair):
    def handler(req):
        if req.url.path.endswith("access_tokens"):
            return token_response()
        return httpx.Response(422, json={"message": "Validation Failed"})

    with pytest.raises(GitHubError) as info:
        client(keypair, handler).comment(7, "x")
    assert info.value.status == 422 and "Validation Failed" in str(info.value)


def test_push_auth_keeps_the_token_out_of_the_url(keypair):
    import base64
    c = client(keypair, lambda req: token_response())
    url, env = c.push_auth()
    assert url == "https://github.com/o/r.git" and "ghs_abc" not in url
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    scheme, encoded = env["GIT_CONFIG_VALUE_0"].removeprefix("AUTHORIZATION: ").split()
    assert scheme == "basic" and base64.b64decode(encoded) == b"x-access-token:ghs_abc"
    assert not hasattr(c, "push_url")


def test_list_issues_pages_and_skips_pull_requests(keypair):
    def handler(req):
        if req.url.path.endswith("access_tokens"):
            return token_response()
        assert req.url.params["labels"] == "agent:ready" and req.url.params["state"] == "open"
        page = int(req.url.params["page"])
        if page == 1:
            items = [{"number": n, "title": "t", "body": None, "labels": [{"name": "agent:ready"}],
                      "updated_at": "2026-09-26T10:00:00Z"} for n in range(1, 101)]
            items[0]["pull_request"] = {}
            return httpx.Response(200, json=items)
        return httpx.Response(200, json=[{"number": 101, "title": "t", "body": "b", "labels": [],
                                          "updated_at": ""}])

    issues = client(keypair, handler).list_issues("agent:ready")
    assert [i.number for i in issues] == list(range(2, 102))
    assert issues[0].updated_at == "2026-09-26T10:00:00Z" and issues[0].body == ""


def test_issue_state_open_closed_pr_and_missing(keypair):
    def handler(req):
        if req.url.path.endswith("access_tokens"):
            return token_response()
        n = int(req.url.path.rsplit("/", 1)[1])
        if n == 404:
            return httpx.Response(404, json={"message": "Not Found"})
        body = {"number": n, "title": "t", "labels": [], "state": "closed" if n == 2 else "open"}
        if n == 3:
            body["pull_request"] = {}
        return httpx.Response(200, json=body)

    c = client(keypair, handler)
    assert [c.issue_state(n) for n in (1, 2, 3, 404)] == ["open", "closed", None, None]


def test_labels_prs_and_branch_sha(keypair):
    seen = []

    def handler(req):
        if req.url.path.endswith("access_tokens"):
            return token_response()
        seen.append((req.method, req.url.raw_path.decode(), json.loads(req.content or b"null")))
        if req.url.path == "/repos/o/r/pulls":
            return httpx.Response(200, json=[{"number": 4, "body": "Closes #3"}, {"number": 9, "body": None}])
        if req.url.path == "/repos/o/r/branches/main":
            return httpx.Response(200, json={"commit": {"sha": "f" * 40}})
        if req.method == "DELETE" and "agent%3Amissing" in req.url.raw_path.decode():
            return httpx.Response(404, json={"message": "Label does not exist"})
        return httpx.Response(200, json=[])

    c = client(keypair, handler)
    c.add_labels(5, ["agent:queued"])
    c.remove_label(5, "agent:ready")
    c.remove_label(5, "agent:missing")  # absent label: ignored
    assert c.list_open_pull_requests() == [(4, "Closes #3"), (9, "")]
    assert c.branch_sha() == "f" * 40
    assert seen[0] == ("POST", "/repos/o/r/issues/5/labels", {"labels": ["agent:queued"]})
    assert seen[1][:2] == ("DELETE", "/repos/o/r/issues/5/labels/agent%3Aready")
