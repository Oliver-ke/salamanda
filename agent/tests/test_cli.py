import pytest

from loop_agent.__main__ import make_job_handler, parse_args
from loop_agent.config import Config
from loop_agent.run import Job, RunResult

ENV = {"LOOP_REPO": "o/r", "LOOP_REPO_DIR": "/workspace/repo", "GITHUB_APP_ID": "1",
       "GITHUB_APP_INSTALLATION_ID": "2", "LOOP_BOT_LOGIN": "b[bot]", "LOOP_GIT_AUTHOR_EMAIL": "e"}
JOB = Job("o/r", 7, "a" * 40)


def test_run_requires_issue():
    with pytest.raises(SystemExit):
        parse_args(["run"])
    assert parse_args(["run", "--issue", "7"]).issue == 7


def test_serve_defaults_to_8080():
    assert parse_args(["serve"]).port == 8080


def test_serve_builds_nothing_before_a_job(monkeypatch):
    """The image build starts `serve`; whatever it builds then is frozen into the snapshot."""
    import loop_agent.__main__ as cli
    seen = {}

    class FakeServer:
        def __init__(self, handle, on_done, **kwargs):
            seen.update(kwargs)

        def serve_forever(self):
            seen["served"] = True

    def boom(*a, **k):
        raise AssertionError("nothing may be built before a job arrives")

    monkeypatch.setenv("LOOP_REPO", "o/r")
    monkeypatch.setattr(cli.Config, "from_env", classmethod(boom))
    monkeypatch.setattr(cli, "build_deps", boom)
    monkeypatch.setattr(cli, "JobServer", FakeServer)
    assert cli.main(["serve", "--port", "9"]) == 0
    assert seen == {"expected_repo": "o/r", "port": 9, "once": True, "served": True}


def test_job_secrets_become_the_config():
    captured = {}

    def build(config):
        captured["config"] = config
        return "deps"

    handle = make_job_handler(ENV, build=build, run=lambda job, deps: RunResult("pr_opened", "u", deps))
    result = handle(JOB, {"anthropic_api_key": "sk-ant-x", "github_app_private_key": "PEM"})
    assert result.detail == "deps"
    assert captured["config"].anthropic_api_key == "sk-ant-x"
    assert captured["config"].github_private_key == "PEM"


def test_config_error_never_contains_a_secret():
    handle = make_job_handler({**ENV, "LOOP_BOT_LOGIN": "not-a-bot"}, build=lambda c: None,
                              run=lambda j, d: None)
    result = handle(JOB, {"anthropic_api_key": "sk-ant-SECRET", "github_app_private_key": "PEM-SECRET"})
    assert result.outcome == "error" and result.detail.startswith("configuration:")
    assert "SECRET" not in result.detail


def test_missing_secrets_are_a_configuration_error():
    result = make_job_handler(ENV, build=lambda c: None, run=lambda j, d: None)(JOB, {})
    assert result.outcome == "error" and "ANTHROPIC_API_KEY" in result.detail


def test_serve_without_loop_repo_exits_2(monkeypatch):
    import loop_agent.__main__ as cli
    monkeypatch.delenv("LOOP_REPO", raising=False)
    assert cli.main(["serve"]) == 2
