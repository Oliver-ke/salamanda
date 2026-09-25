import subprocess

import pytest

from loop_agent.commands import (CommandRejected, as_user, child_env, parse_allowed,
                                 run_allowed)


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
