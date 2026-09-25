"""The only commands the agent may run. No shell: argv is matched exactly."""

import os
import re
import shlex
import signal
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

EXACT = {("npm", "run", script) for script in ("verify", "test", "typecheck", "lint", "build")}
SINGLE_TEST = ["npm", "run", "test", "--workspace", "app", "--"]
TEST_FILE = re.compile(r"^src/[A-Za-z0-9_./-]+\.test\.tsx?$")
SECRET_PREFIXES = ("AWS_", "GITHUB_APP_", "BEDROCK_", "LOOP_")
OUTPUT_TAIL = 8000
ALLOWED_HELP = ("allowed: npm run verify|test|typecheck|lint|build, "
                "or npm run test --workspace app -- src/<path>.test.ts(x)")


class CommandRejected(Exception):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    output: str


def parse_allowed(cmd: str) -> list[str]:
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        raise CommandRejected(f"{cmd!r} could not be parsed: {exc}") from exc
    if tuple(argv) in EXACT:
        return argv
    if (len(argv) == len(SINGLE_TEST) + 1 and argv[:-1] == SINGLE_TEST
            and TEST_FILE.match(argv[-1]) and ".." not in argv[-1]):
        return argv
    raise CommandRejected(f"{cmd!r} is not an allowed command; {ALLOWED_HELP}")


def child_env(env: Mapping[str, str], command_user: str | None = None) -> dict[str, str]:
    """Agent-run commands execute agent-written code with network access, so they
    never see the worker's credentials. As the command user they also get that
    user's HOME, never the worker's."""
    scrubbed = {k: v for k, v in env.items() if not k.startswith(SECRET_PREFIXES)}
    scrubbed["CI"] = "1"
    if command_user is not None:
        scrubbed["HOME"] = f"/home/{command_user}"
        scrubbed["USER"] = command_user
    return scrubbed


def as_user(argv: list[str], command_user: str | None) -> list[str]:
    if command_user is None:
        return argv
    return ["setpriv", f"--reuid={command_user}", f"--regid={command_user}",
            "--init-groups", "--", *argv]


def _kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_in_group(argv: list[str], *, cwd: Path, env: Mapping[str, str],
                 timeout: float) -> tuple[int, str]:
    """Run argv as the leader of a new process group, and kill the whole group once
    it exits or times out: nothing the command starts outlives it. Output goes to a
    file, not a pipe, so a background child holding stdout cannot stall the wait.
    Raises subprocess.TimeoutExpired (after the kill) on timeout."""
    with tempfile.TemporaryFile() as out:
        proc = subprocess.Popen(argv, cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc.pid)
            proc.wait()
            raise
        finally:
            _kill_group(proc.pid)
        out.seek(0)
        return code, out.read().decode("utf-8", errors="replace")


def grouped_run(argv: list[str], *, cwd: Path, env: Mapping[str, str], timeout: float,
                **_ignored) -> subprocess.CompletedProcess:
    """run_in_group behind the subprocess.run-shaped seam the tests inject."""
    code, output = run_in_group(argv, cwd=cwd, env=env, timeout=timeout)
    return subprocess.CompletedProcess(argv, code, stdout=output, stderr="")


def run_allowed(cmd: str, cwd: Path, *, timeout: int = 900,
                command_user: str | None = None, runner=grouped_run) -> CommandResult:
    argv = parse_allowed(cmd)
    try:
        proc = runner(as_user(argv, command_user), cwd=cwd, timeout=timeout,
                      env=child_env(os.environ, command_user))
    except subprocess.TimeoutExpired:
        return CommandResult(cmd, 124, f"timed out after {timeout}s")
    output = (proc.stdout or "") + (proc.stderr or "")
    return CommandResult(cmd, proc.returncode, output[-OUTPUT_TAIL:])
