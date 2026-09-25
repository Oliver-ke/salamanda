"""Strands + Bedrock. The only module that talks to the model."""

from strands import Agent
from strands.models import BedrockModel

from .toolbox import AgentOutcome, Toolbox
from .tools import make_tools


class StrandsSession:
    def __init__(self, agent: Agent, toolbox: Toolbox):
        self.agent, self.toolbox = agent, toolbox

    def send(self, prompt: str) -> AgentOutcome:
        self.toolbox.begin_turn()
        self.agent(prompt)
        return self.toolbox.outcome()


class StrandsAgentRunner:
    def __init__(self, model_id: str, region: str, system_prompt: str, max_tokens: int = 8192):
        self.model_id, self.region = model_id, region
        self.system_prompt, self.max_tokens = system_prompt, max_tokens

    def session(self, toolbox: Toolbox) -> StrandsSession:
        model = BedrockModel(model_id=self.model_id, region_name=self.region, max_tokens=self.max_tokens)
        agent = Agent(model=model, system_prompt=self.system_prompt,
                      tools=make_tools(toolbox), callback_handler=None)
        return StrandsSession(agent, toolbox)
