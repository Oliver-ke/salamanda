import pytest

from loop_agent.config import Config, ConfigError

BASE = {
    "LOOP_MODEL_PROVIDER": "bedrock",
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
        Config.from_env({"LOOP_REPO": "o/r", "LOOP_MODEL_PROVIDER": "bedrock"})
    for name in ("LOOP_REPO_DIR", "BEDROCK_MODEL_ID", "GITHUB_APP_ID", "LOOP_BOT_LOGIN"):
        assert name in str(info.value)


def test_private_key_from_file(tmp_path):
    key = tmp_path / "app.pem"
    key.write_text("FILE-PEM")
    key.chmod(0o600)
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


def _key_file_env(path):
    env = {k: v for k, v in BASE.items() if k != "GITHUB_APP_PRIVATE_KEY"}
    env["GITHUB_APP_PRIVATE_KEY_FILE"] = str(path)
    return env


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_private_key_file_readable_by_others_is_an_error(tmp_path, mode):
    key = tmp_path / "app.pem"
    key.write_text("FILE-PEM")
    key.chmod(mode)
    with pytest.raises(ConfigError, match="chmod 600"):
        Config.from_env(_key_file_env(key))


def test_missing_private_key_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="GITHUB_APP_PRIVATE_KEY_FILE"):
        Config.from_env(_key_file_env(tmp_path / "nope.pem"))


def test_bot_login_must_be_a_bot():
    with pytest.raises(ConfigError, match=r"\[bot\]"):
        Config.from_env({**BASE, "LOOP_BOT_LOGIN": "loop-sdlc"})


def test_non_numeric_max_tool_calls_is_a_config_error():
    with pytest.raises(ConfigError, match="LOOP_MAX_TOOL_CALLS"):
        Config.from_env({**BASE, "LOOP_MAX_TOOL_CALLS": "lots"})
    assert Config.from_env({**BASE, "LOOP_MAX_TOOL_CALLS": "12"}).max_tool_calls == 12


ANTHROPIC = {k: v for k, v in BASE.items()
             if k not in ("LOOP_MODEL_PROVIDER", "BEDROCK_MODEL_ID", "AWS_REGION")}


def test_anthropic_direct_is_the_default_provider():
    c = Config.from_env({**ANTHROPIC, "ANTHROPIC_API_KEY": "sk-ant-test"})
    assert c.model_provider == "anthropic"
    assert c.model_id == "claude-opus-5-5"
    assert c.anthropic_api_key == "sk-ant-test"
    assert c.effort == "high"
    assert c.aws_region is None


def test_anthropic_model_and_effort_can_be_set():
    c = Config.from_env({**ANTHROPIC, "ANTHROPIC_API_KEY": "k", "LOOP_MODEL_ID": "claude-sonnet-5",
                         "LOOP_EFFORT": "xhigh"})
    assert (c.model_id, c.effort) == ("claude-sonnet-5", "xhigh")


def test_anthropic_requires_an_api_key():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        Config.from_env(ANTHROPIC)


def test_anthropic_key_from_file_must_be_private(tmp_path):
    key = tmp_path / "anthropic.key"
    key.write_text("sk-ant-file\n")
    key.chmod(0o644)
    with pytest.raises(ConfigError, match="chmod 600"):
        Config.from_env({**ANTHROPIC, "ANTHROPIC_API_KEY_FILE": str(key)})
    key.chmod(0o600)
    assert Config.from_env({**ANTHROPIC, "ANTHROPIC_API_KEY_FILE": str(key)}).anthropic_api_key == "sk-ant-file"


def test_bedrock_provider_requires_model_and_region():
    env = {**ANTHROPIC, "LOOP_MODEL_PROVIDER": "bedrock"}
    with pytest.raises(ConfigError) as info:
        Config.from_env(env)
    assert "BEDROCK_MODEL_ID" in str(info.value) and "AWS_REGION" in str(info.value)


@pytest.mark.parametrize("name,value", [("LOOP_MODEL_PROVIDER", "openai"), ("LOOP_EFFORT", "extreme")])
def test_rejects_unknown_provider_or_effort(name, value):
    with pytest.raises(ConfigError, match=name):
        Config.from_env({**ANTHROPIC, "ANTHROPIC_API_KEY": "k", name: value})
