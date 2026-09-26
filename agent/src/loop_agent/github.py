"""GitHub REST as the loop's GitHub App: issues, comments, pull requests."""

import base64
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

import httpx
import jwt

API = "https://api.github.com"
REFRESH_MARGIN_S = 300


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    labels: list[str]
    updated_at: str = ""


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str


class GitHubError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def _issue(data: dict) -> Issue:
    return Issue(data["number"], data["title"], data.get("body") or "",
                 [label["name"] for label in data.get("labels", [])], data.get("updated_at") or "")


class GitHubAppClient:
    def __init__(self, repo: str, app_id: str, private_key_pem: str, installation_id: str,
                 http: httpx.Client | None = None, clock=time.time):
        self.repo = repo
        self.app_id = app_id
        self.private_key_pem = private_key_pem
        self.installation_id = installation_id
        self.http = http or httpx.Client(timeout=30)
        self.clock = clock
        self._token: str | None = None
        self._token_expires = 0.0

    def installation_token(self) -> str:
        now = self.clock()
        if self._token and now < self._token_expires - REFRESH_MARGIN_S:
            return self._token
        app_jwt = jwt.encode({"iat": int(now) - 60, "exp": int(now) + 540, "iss": self.app_id},
                             self.private_key_pem, algorithm="RS256")
        data = self._send("POST", f"/app/installations/{self.installation_id}/access_tokens",
                          auth=f"Bearer {app_jwt}")
        self._token = data["token"]
        self._token_expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
        return self._token

    def _send(self, method: str, path: str, *, auth: str | None = None, json: dict | None = None) -> dict:
        headers = {"accept": "application/vnd.github+json", "x-github-api-version": "2022-11-28",
                   "authorization": auth or f"Bearer {self.installation_token()}"}
        resp = self.http.request(method, f"{API}{path}", headers=headers, json=json)
        if resp.status_code >= 400:
            try:
                message = resp.json().get("message", resp.text)
            except ValueError:
                message = resp.text
            raise GitHubError(f"GitHub {method} {path} → {resp.status_code}: {message}", resp.status_code)
        return resp.json() if resp.content else {}

    def get_issue(self, number: int) -> Issue:
        data = self._send("GET", f"/repos/{self.repo}/issues/{number}")
        if "pull_request" in data:
            raise GitHubError(f"#{number} is a pull request, not an issue")
        return _issue(data)

    def create_issue(self, title: str, body: str, labels: list[str]) -> int:
        data = self._send("POST", f"/repos/{self.repo}/issues",
                          json={"title": title, "body": body, "labels": labels})
        return data["number"]

    def comment(self, number: int, body: str) -> None:
        self._send("POST", f"/repos/{self.repo}/issues/{number}/comments", json={"body": body})

    def open_pull_request(self, head: str, base: str, title: str, body: str) -> PullRequest:
        data = self._send("POST", f"/repos/{self.repo}/pulls",
                          json={"head": head, "base": base, "title": title, "body": body})
        return PullRequest(data["number"], data["html_url"])

    def _pages(self, path: str) -> list[dict]:
        items, page = [], 1
        sep = "&" if "?" in path else "?"
        while True:
            batch = self._send("GET", f"{path}{sep}per_page=100&page={page}")
            items += batch
            if len(batch) < 100:
                return items
            page += 1

    def list_issues(self, label: str) -> list[Issue]:
        rows = self._pages(f"/repos/{self.repo}/issues?state=open&labels={quote(label, safe='')}")
        return [_issue(row) for row in rows if "pull_request" not in row]

    def issue_state(self, number: int) -> str | None:
        try:
            data = self._send("GET", f"/repos/{self.repo}/issues/{number}")
        except GitHubError as exc:
            if exc.status == 404:
                return None
            raise
        return None if "pull_request" in data else data["state"]

    def list_open_pull_requests(self) -> list[tuple[int, str]]:
        return [(row["number"], row.get("body") or "")
                for row in self._pages(f"/repos/{self.repo}/pulls?state=open")]

    def add_labels(self, number: int, labels: list[str]) -> None:
        self._send("POST", f"/repos/{self.repo}/issues/{number}/labels", json={"labels": labels})

    def remove_label(self, number: int, label: str) -> None:
        try:
            self._send("DELETE", f"/repos/{self.repo}/issues/{number}/labels/{quote(label, safe='')}")
        except GitHubError as exc:
            if exc.status != 404:
                raise

    def branch_sha(self, branch: str = "main") -> str:
        return self._send("GET", f"/repos/{self.repo}/branches/{branch}")["commit"]["sha"]

    def push_auth(self) -> tuple[str, dict[str, str]]:
        """Push URL plus the git environment that authenticates it. The token goes
        in the environment, never the URL: argv is readable by every process."""
        basic = base64.b64encode(f"x-access-token:{self.installation_token()}".encode()).decode()
        return f"https://github.com/{self.repo}.git", {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        }
