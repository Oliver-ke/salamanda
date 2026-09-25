"""HTTP front door for one worker: one job at a time, for one repository."""

import json
import re
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .run import Job, RunResult

SHA = re.compile(r"^[0-9a-f]{40}$")


def parse_job(payload: object, expected_repo: str) -> Job:
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    repo, issue, sha = payload.get("repo"), payload.get("issue"), payload.get("sha")
    if repo != expected_repo:
        raise ValueError(f"repo must be {expected_repo}")
    if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
        raise ValueError("issue must be a positive integer")
    if not isinstance(sha, str) or not SHA.match(sha):
        raise ValueError("sha must be a 40-character hex commit id")
    return Job(repo, issue, sha)


class JobServer:
    def __init__(self, handle: Callable[[Job], RunResult],
                 on_done: Callable[[Job, RunResult], None], expected_repo: str,
                 host: str = "0.0.0.0", port: int = 8080, once: bool = False):
        self.handle, self.on_done, self.expected_repo = handle, on_done, expected_repo
        # once: one job per server lifetime (production runs one MicroVM per task,
        # so nothing a job leaves behind can reach the next one).
        self.once = once
        self._lock = threading.Lock()
        self._busy = False
        self._httpd = ThreadingHTTPServer((host, port), self._handler_class())
        self.port = self._httpd.server_address[1]
        self._thread: threading.Thread | None = None

    def _claim(self) -> bool:
        with self._lock:
            if self._busy:
                return False
            self._busy = True
            return True

    def _work(self, job: Job) -> None:
        try:
            self.on_done(job, self.handle(job))
        finally:
            if self.once:
                # Stay busy: no second job slips in before the shutdown lands.
                threading.Thread(target=self._httpd.shutdown, daemon=True).start()
            else:
                with self._lock:
                    self._busy = False

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

            def do_GET(self):
                if self.path == "/health":
                    return self._reply(200, {"busy": server._busy})
                self._reply(404, {"error": "not found"})

            def do_POST(self):
                if self.path != "/jobs":
                    return self._reply(404, {"error": "not found"})
                try:
                    length = int(self.headers.get("content-length", "0"))
                    job = parse_job(json.loads(self.rfile.read(length) or b"null"), server.expected_repo)
                except (ValueError, json.JSONDecodeError) as exc:
                    return self._reply(400, {"error": str(exc)})
                if not server._claim():
                    return self._reply(409, {"error": "worker is busy with another job"})
                threading.Thread(target=server._work, args=(job,), daemon=True).start()
                self._reply(202, {"accepted": True})

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
