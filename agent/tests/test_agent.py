from dataclasses import replace
from pathlib import Path

from strands.models import BedrockModel
from strands.models.anthropic import AnthropicModel

from loop_agent.agent import MAX_TOKENS, build_model
from loop_agent.config import Config

CONFIG = Config(repo="o/r", repo_dir=Path("/r"), model_provider="anthropic", model_id="claude-opus-5-5",
                aws_region=None, anthropic_api_key="sk-ant-test", effort="high",
                github_app_id="1", github_installation_id="2", github_private_key="PEM",
                bot_login="b[bot]", git_author_email="e")


def test_anthropic_provider_builds_a_direct_model_with_explicit_effort():
    model = build_model(CONFIG)
    assert isinstance(model, AnthropicModel)
    cfg = model.get_config()
    assert cfg["model_id"] == "claude-opus-5-5"
    assert cfg["max_tokens"] == MAX_TOKENS
    assert cfg["params"] == {"output_config": {"effort": "high"}}


def test_bedrock_provider_builds_a_bedrock_model():
    model = build_model(replace(CONFIG, model_provider="bedrock", model_id="eu.anthropic.claude-opus-5-5",
                                aws_region="eu-west-1", anthropic_api_key=None))
    assert isinstance(model, BedrockModel)
    assert model.get_config()["model_id"] == "eu.anthropic.claude-opus-5-5"
