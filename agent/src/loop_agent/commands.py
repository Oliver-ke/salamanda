"""The only commands the agent may run. No shell: argv is matched exactly."""

import os
import re
import shlex
import subprocess
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


def child_env(env: Mapping[str, str]) -> dict[str, str]:
    """Agent-run commands execute agent-written code with network access, so they
    never see the worker's credentials."""
    scrubbed = {k: v for k, v in env.items() if not k.startswith(SECRET_PREFIXES)}
    scrubbed["CI"] = "1"
    return scrubbed


def as_user(argv: list[str], command_user: str | None) -> list[str]:
    if command_user is None:
        return argv
    return ["setpriv", f"--reuid={command_user}", f"--regid={command_user}",
            "--init-groups", "--", *argv]


def run_allowed(cmd: str, cwd: Path, *, timeout: int = 900,
                command_user: str | None = None, runner=subprocess.run) -> CommandResult:
    argv = parse_allowed(cmd)
    try:
        proc = runner(as_user(argv, command_user), cwd=cwd, capture_output=True,
                      text=True, timeout=timeout, env=child_env(os.environ))
    except subprocess.TimeoutExpired:
        return CommandResult(cmd, 124, f"timed out after {timeout}s")
    output = (proc.stdout or "") + (proc.stderr or "")
    return CommandResult(cmd, proc.returncode, output[-OUTPUT_TAIL:])
