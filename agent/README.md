# agent — the loop worker

Takes one GitHub issue, runs a Strands agent on Claude against this repo, and opens
at most one pull request. See [the worker docs](../docs/worker.md) and [architecture](../docs/architecture.md).

## One-time setup (a human)
1. **GitHub App** (Settings → Developer settings → GitHub Apps → New):
   - Repository permissions: Contents *read & write*, Pull requests *read & write*,
     Issues *read & write*, Metadata *read*. **Workflows: no access.**
   - No webhook. Install it on this repository only.
   - Note the App ID and the installation ID (from the installation URL). Generate a
     private key and save it **outside the repo**, e.g. `~/.config/loop-sdlc/app.pem`,
     then `chmod 600` it. Agent-run commands share the container as the `runner`
     user; the worker refuses a key file that group or others can read. Instead of
     mounting a file you can pass the key itself in `GITHUB_APP_PRIVATE_KEY` (the
     worker strips `GITHUB_APP_*` from every agent-run command's environment).
   - The bot user id for `LOOP_GIT_AUTHOR_EMAIL`: `gh api /users/<app-slug>%5Bbot%5D --jq .id`.
2. **Model access.** The default provider is the Anthropic API directly
   (`LOOP_MODEL_PROVIDER=anthropic`, model `claude-opus-5-5`). Save an API key
   **outside the repo**, e.g. `~/.config/loop-sdlc/anthropic.key`, and `chmod 600` it;
   the worker refuses a key file that group or others can read, and strips
   `ANTHROPIC_*` from every agent-run command's environment. To use Amazon Bedrock
   instead, set `LOOP_MODEL_PROVIDER=bedrock`, `BEDROCK_MODEL_ID` and `AWS_REGION`, and
   pass AWS credentials to the container.
3. **Labels:**
   ```bash
   gh label create agent:ready --color 0E8A16 --description "Approved for the loop agent"
   gh label create agent:queued --color FBCA04
   gh label create agent:running --color 1D76DB
   gh label create agent:failed --color D93F0B
   gh label create agent:too-big --color 5319E7
   gh label create priority:high --color B60205
   gh label create priority:low --color C2E0C6
   ```

## Run one issue locally
`~/.config/loop-sdlc/worker.env` (never committed):
```
LOOP_REPO=Oliver-ke/salamanda
LOOP_MODEL_PROVIDER=anthropic
LOOP_MODEL_ID=claude-opus-5-5
LOOP_EFFORT=high
ANTHROPIC_API_KEY_FILE=/run/secrets/anthropic.key
GITHUB_APP_ID=<id>
GITHUB_APP_INSTALLATION_ID=<id>
GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/app.pem
LOOP_BOT_LOGIN=<app-slug>[bot]
LOOP_GIT_AUTHOR_EMAIL=<bot-user-id>+<app-slug>[bot]@users.noreply.github.com
```
```bash
docker build -f agent/Dockerfile -t loop-worker .
docker run --rm --init \
  --env-file ~/.config/loop-sdlc/worker.env \
  -v ~/.config/loop-sdlc/app.pem:/run/secrets/app.pem:ro \
  -v ~/.config/loop-sdlc/anthropic.key:/run/secrets/anthropic.key:ro \
  loop-worker /opt/agent-venv/bin/python -m loop_agent run --issue <N>
```
(With `LOOP_MODEL_PROVIDER=bedrock`, add
`--env-file <(aws configure export-credentials --format env-no-export)` for AWS credentials.)
Exit code 0 means a pull request was opened; the JSON line on stdout says what happened.
Stop a run with Ctrl-C. A pull request is opened only when `npm run verify` and the
guardrail check both pass. If verify still fails after the retries but the guardrail
passes, the work in progress is pushed to its `agent/issue-N-…` branch for inspection,
and no pull request is opened. Each attempt pushes a new branch and never overwrites one:
if a retry against the same `main` finds its branch already on GitHub (for example under
an open pull request), the push fails and the run reports an error — delete that branch
or wait for `main` to move before retrying.

`--init` reaps the processes the worker kills after each agent command. The worker
refuses to run git unless `.git` is a real directory it owns, so git worktree and
submodule checkouts (where `.git` is a file) are not supported.

## Serve
`python -m loop_agent serve --port 8080` is the MicroVM entry point.
- It answers the build-time `/aws/lambda-microvms/runtime/v1/ready` hook on any method.
- It reads only `LOOP_REPO` at startup, so nothing is built into the snapshot.
- It accepts exactly one job, `POST /jobs {repo, issue, sha, secrets}`. Config and deps are built from the image environment plus the job's `secrets` (`anthropic_api_key`, `github_app_private_key`).
- It reports progress on `GET /jobs/current`.
- It stays up afterwards so the result can be read, and refuses a second job.

The secrets are held in memory only, never logged or returned. The MicroVM runs with no AWS execution role.

## Tests
`cd agent && uv run pytest -q`
