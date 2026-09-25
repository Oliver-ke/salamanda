import pytest

from loop_agent.config import Config, ConfigError

BASE = {
    "LOOP_REPO": "o/r", "LOOP_REPO_DIR": "/workspace/repo", "BEDROCK_MODEL_ID": "m",
    "AWS_REGION": "us-east-1", "GITHUB_APP_ID": "1", "GITHUB_APP_INSTALLATION_ID": "2",
    "GITHUB_APP_PRIVATE_KEY": "PEM", "LOOP_BOT_LOGIN": "loop-sdlc[bot]",
    "LOOP_GIT_AUTHOR_EMAIL": "1+loop-sdlc[bot]@users.noreply.github.com",
}


def test_reads_required_and_defaults():
    c = Config.from_env(BASE)
    assert c.repo == "o/r" and str(c.repo_dir) == "/workspace/repo"
    assert c.max_tool_calls == 60 and c.snapshot_lock_file is None and c.command_user is None


def test_lists_every_missing_variable():
    with pytest.raises(ConfigError) as info:
        Config.from_env({"LOOP_REPO": "o/r"})
    for name in ("LOOP_REPO_DIR", "BEDROCK_MODEL_ID", "GITHUB_APP_ID", "LOOP_BOT_LOGIN"):
        assert name in str(info.value)


def test_private_key_from_file(tmp_path):
    key = tmp_path / "app.pem"
    key.write_text("FILE-PEM")
    env = {k: v for k, v in BASE.items() if k != "GITHUB_APP_PRIVATE_KEY"}
    env["GITHUB_APP_PRIVATE_KEY_FILE"] = str(key)
    assert Config.from_env(env).github_private_key == "FILE-PEM"


def test_missing_private_key_is_an_error():
    env = {k: v for k, v in BASE.items() if k != "GITHUB_APP_PRIVATE_KEY"}
    with pytest.raises(ConfigError, match="GITHUB_APP_PRIVATE_KEY"):
        Config.from_env(env)


def test_bad_repo_is_an_error():
    with pytest.raises(ConfigError, match="owner/name"):
        Config.from_env({**BASE, "LOOP_REPO": "not-a-repo"})
