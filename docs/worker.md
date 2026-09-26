# The worker

The worker is the Python package in `agent/` (`loop_agent`). It runs inside the MicroVM image and does
one issue per run. The same code runs locally in Docker (see [Development](development.md)).

## Entry points

| Command | Used for |
|---|---|
| `python -m loop_agent serve --port 8080` | The MicroVM entry point: an HTTP server that accepts one job |
| `python -m loop_agent run --issue N [--sha SHA]` | A foreground run of one issue (local testing) |

**`serve`** builds nothing at startup: no configuration, no clients, no secrets. The MicroVM image is a
snapshot taken after `serve` starts, and anything built earlier would be frozen into every MicroVM.

HTTP endpoints:

| Endpoint | Behaviour |
|---|---|
| `POST /jobs {repo, issue, sha, secrets}` | 202 accepted; 400 for an invalid job or the wrong repo; 409 if busy or the job was already used |
| `GET /jobs/current` | `{"state": "idle" \| "running" \| "done", "result": {...}}` |
| `GET /health` | `{"busy": bool}` |
| any `/aws/lambda-microvms/runtime/v1/*` | 200: the platform's build-time readiness hook |

Configuration is built **per job**, from the image's environment plus the job's `secrets`
(`anthropic_api_key`, `github_app_private_key`). Secrets stay in memory. They are never logged or returned,
and they are masked out of any error text.

## One run, step by step

1. **Prepare.**
   - Fetch `main`, then check out the queued `sha` on the branch `agent/issue-<N>-<slug>-<sha7>`.
   - Run `npm ci` only if the lockfile differs from the image snapshot's.
   - Hand the working tree to the unprivileged `runner` user. `.git` stays owned by root.
2. **Agent.** A [Strands](https://strandsagents.com) agent runs on Claude Opus 5.5 at effort `high`. Its
   system prompt is `agent/prompt.md` plus the repository's `CLAUDE.md`, and it gets the issue as requirements.
3. **Verify.** When the agent calls `finish`, the worker runs `npm run verify` itself: typecheck, lint,
   tests, build. On failure it hands the output back to the agent, up to 2 retries.
4. **Guardrail pre-check.** The worker commits, then runs the same `pr-rules` check CI runs. It takes the
   checker from the **base** commit, never the working tree, so the change can't rewrite its own judge.
5. **Publish.**
   1. Push the branch. The push fails rather than overwrite an existing branch.
   2. Open the PR, with a body starting `Closes #N`.
   3. Comment the PR link on the issue.
6. **Report.** The result (`pr_opened`, `gave_up`, `verify_failed`, `guardrail_failed`, `no_changes` or
   `error`) goes to `/jobs/current` for Step Functions to read.

## The agent's tools

The agent has **no shell, no git, and no network tool**. The worker owns git and GitHub.

| Tool | What it does | Limits |
|---|---|---|
| `read_file`, `list_files`, `search` | Read the repository | Confined to the repo; `.git/` and `node_modules/` refused; symlinks resolved and refused if they escape |
| `write_file` | Create or overwrite a file | Also refuses [protected paths](security.md#protected-paths) |
| `run` | Run one command | Only `npm run verify\|test\|typecheck\|lint\|build` or `npm run test --workspace app -- src/<file>.test.ts(x)`; runs as `runner` with a scrubbed environment |
| `file_child_issue` | File a smaller follow-up issue | At most 5 per run; filed without `agent:ready` |
| `finish` / `give_up` | End the turn with a summary or a reason | — |

**Budget:** 60 tool calls per run (`LOOP_MAX_TOOL_CALLS`). After that, every tool refuses, but `finish`
and `give_up` still work.

## Where the code lives

| Module | Responsibility |
|---|---|
| `config.py` | Environment → `Config`; secrets from variables or `*_FILE`; provider selection |
| `sandbox.py`, `protected.py` | The repo-confined workspace and the protected-path list (read from `harness/`) |
| `commands.py` | The command allowlist, environment scrubbing, running as `runner`, process-group and user sweeps |
| `toolbox.py`, `tools.py` | Tool logic and the Strands tool wrappers |
| `agent.py` | Builds the model (Anthropic or Bedrock) and the agent session |
| `gitops.py` | Git with hooks disabled, credential redaction, never-overwrite pushes |
| `github.py` | The GitHub App client: tokens, issues, labels, PRs |
| `prompts.py`, `checks.py` | Prompts and PR body; dependency install, verify, guardrail pre-check |
| `run.py` | `run_job`: one issue in, at most one PR out |
| `server.py`, `__main__.py`, `wiring.py` | HTTP server, CLI, and dependency wiring |
| `aws/` | Intake, selection, backoff, the task Lambdas, the MicroVM helper, the state machine definition |
| `deploy/` | `build_image.py` (the MicroVM image) and `package_lambdas.sh` (the Lambda zip) |
