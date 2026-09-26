# Salamanda documentation

Salamanda is an agentic harness: a closed loop that turns approved GitHub issues into
reviewed pull requests, with an AI agent doing the work inside an isolated AWS Lambda MicroVM.

| Document | Read it to… |
|---|---|
| [Overview](overview.md) | understand what the loop does and the ideas behind it |
| [Architecture](architecture.md) | see every component, how a run flows through them, and why each exists |
| [Writing issues](issues.md) | write issues the agent can do, and follow an issue through its labels |
| [The worker](worker.md) | learn what happens inside one run: the agent, its tools, and how a PR is made |
| [Security and guardrails](security.md) | see what stops the agent (or a bad issue) from doing damage |
| [Operations](operations.md) | deploy, run, pause, stop, and troubleshoot the loop |
| [Configuration](configuration.md) | look up every setting: worker environment, Terraform variables, labels |
| [Development](development.md) | work on this repository: layout, tests, CI, running the worker locally |
