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
