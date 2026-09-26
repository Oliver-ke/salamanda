"""HTTP front door for one worker: one job at a time, for one repository."""

import json
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .run import Job, RunResult

SHA = re.compile(r"^[0-9a-f]{40}$")
HOOK_PREFIX = "/aws/lambda-microvms/runtime/v1/"
SECRET_KEYS = ("anthropic_api_key", "github_app_private_key")
MAX_BODY = 64 * 1024


def parse_request(payload: object, expected_repo: str) -> tuple[Job, dict[str, str]]:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    repo, issue, sha = payload.get("repo"), payload.get("issue"), payload.get("sha")
    if repo != expected_repo:
        raise ValueError(f"repo must be {expected_repo}")
    if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
        raise ValueError("issue must be a positive integer")
    if not isinstance(sha, str) or not SHA.match(sha):
        raise ValueError("sha must be a 40-character hex commit id")
    secrets = payload.get("secrets") or {}
    if not isinstance(secrets, dict) or not all(
            key in SECRET_KEYS and isinstance(value, str) and value for key, value in secrets.items()):
        raise ValueError(f"secrets must map {', '.join(SECRET_KEYS)} to non-empty strings")
    return Job(repo, issue, sha), dict(secrets)


class JobServer:
    def __init__(self, handle: Callable[[Job, Mapping[str, str]], RunResult],
                 on_done: Callable[[Job, RunResult], None], expected_repo: str,
                 host: str = "0.0.0.0", port: int = 8080, once: bool = False):
        self.handle, self.on_done, self.expected_repo = handle, on_done, expected_repo
        # once: one job per server lifetime (one MicroVM per task, so nothing a job
        # leaves behind reaches the next). The server stays up so its result can
        # still be polled; it just refuses a second job.
        self.once = once
        self._lock = threading.Lock()
        self._state = "idle"
        self._result: dict | None = None
        self._used = False
        self._httpd = ThreadingHTTPServer((host, port), self._handler_class())
        self.port = self._httpd.server_address[1]
        self._thread: threading.Thread | None = None

    def _claim(self) -> str | None:
        """None when the job may start, otherwise why not."""
        with self._lock:
            if self._state == "running":
                return "worker is busy with another job"
            if self.once and self._used:
                return "this worker has already run its job"
            self._state, self._result, self._used = "running", None, True
            return None

    def _work(self, job: Job, secrets: Mapping[str, str]) -> None:
        try:
            result = self.handle(job, secrets)
        except Exception as exc:  # report, never leave the job "running" forever
            detail = f"{type(exc).__name__}: {exc}"
            for value in secrets.values():
                if value:
                    detail = detail.replace(value, "***")
            result = RunResult("error", None, detail)
        with self._lock:
            self._result, self._state = asdict(result), "done"
        self.on_done(job, result)

    def status(self) -> dict:
        with self._lock:
            return {"state": self._state, "result": self._result}

    def _handler_class(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self) -> bytes:
                length = int(self.headers.get("content-length") or 0)
                if length < 0 or length > MAX_BODY:
                    raise ValueError(f"content-length must be between 0 and {MAX_BODY}")
                return self.rfile.read(length) if length else b""

            def _hook(self) -> bool:
                if not self.path.startswith(HOOK_PREFIX):
                    return False
                try:
                    self._body()
                except ValueError:
                    pass
                self._reply(200, {})
                return True

            def do_GET(self):
                if self._hook():
                    return
                if self.path == "/health":
                    return self._reply(200, {"busy": server.status()["state"] == "running"})
                if self.path == "/jobs/current":
                    return self._reply(200, server.status())
                self._reply(404, {"error": "not found"})

            def do_POST(self):
                if self._hook():
                    return
                if self.path != "/jobs":
                    return self._reply(404, {"error": "not found"})
                try:
                    job, secrets = parse_request(json.loads(self._body() or b"null"), server.expected_repo)
                except (ValueError, json.JSONDecodeError) as exc:
                    return self._reply(400, {"error": str(exc)})
                refusal = server._claim()
                if refusal:
                    return self._reply(409, {"error": refusal})
                threading.Thread(target=server._work, args=(job, secrets), daemon=True).start()
                self._reply(202, {"accepted": True})

            def do_PUT(self):
                if not self._hook():
                    self._reply(404, {"error": "not found"})

            def log_message(self, fmt, *args):
                pass

        return Handler

    def start(self) -> None:
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def serve_forever(self) -> None:
        self._httpd.serve_forever()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
