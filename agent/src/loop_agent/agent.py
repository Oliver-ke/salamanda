"""Strands + the model provider. The only module that talks to the model."""

from collections.abc import Callable

from strands import Agent
from strands.models import BedrockModel, Model
from strands.models.anthropic import AnthropicModel

from .config import Config
from .toolbox import AgentOutcome, Toolbox
from .tools import make_tools

# Strands streams, so a large cap does not risk an HTTP timeout; thinking counts
# against it on every turn.
MAX_TOKENS = 32000


def build_model(config: Config) -> Model:
    if config.model_provider == "anthropic":
        # Effort is set explicitly: Claude Opus 5.5 defaults to "medium".
        return AnthropicModel(client_args={"api_key": config.anthropic_api_key},
                              model_id=config.model_id, max_tokens=MAX_TOKENS,
                              params={"output_config": {"effort": config.effort}})
    return BedrockModel(model_id=config.model_id, region_name=config.aws_region, max_tokens=MAX_TOKENS)


class StrandsSession:
    def __init__(self, agent: Agent, toolbox: Toolbox):
        self.agent, self.toolbox = agent, toolbox

    def send(self, prompt: str) -> AgentOutcome:
        self.toolbox.begin_turn()
        self.agent(prompt)
        return self.toolbox.outcome()


class StrandsAgentRunner:
    def __init__(self, model_factory: Callable[[], Model], system_prompt: str):
        self.model_factory, self.system_prompt = model_factory, system_prompt

    def session(self, toolbox: Toolbox) -> StrandsSession:
        agent = Agent(model=self.model_factory(), system_prompt=self.system_prompt,
                      tools=make_tools(toolbox), callback_handler=None)
        return StrandsSession(agent, toolbox)
