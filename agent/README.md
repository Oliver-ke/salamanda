# agent — the loop worker

Takes one GitHub issue, runs a Strands agent on Bedrock against this repo, and opens
at most one pull request. Design: `docs/superpowers/specs/2026-09-25-lambda-microvm-loop-design.md`.

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
2. **Bedrock:** enable access to the model named in the spike findings, in that region.
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
LOOP_REPO=Oliver-ke/loop-sdlc
BEDROCK_MODEL_ID=<from spike findings>
AWS_REGION=<from spike findings>
GITHUB_APP_ID=<id>
GITHUB_APP_INSTALLATION_ID=<id>
GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/app.pem
LOOP_BOT_LOGIN=<app-slug>[bot]
LOOP_GIT_AUTHOR_EMAIL=<bot-user-id>+<app-slug>[bot]@users.noreply.github.com
```
```bash
docker build -f agent/Dockerfile -t loop-worker .
docker run --rm \
  --env-file ~/.config/loop-sdlc/worker.env \
  --env-file <(aws configure export-credentials --format env-no-export) \
  -v ~/.config/loop-sdlc/app.pem:/run/secrets/app.pem:ro \
  loop-worker /opt/agent-venv/bin/python -m loop_agent run --issue <N>
```
Exit code 0 means a pull request was opened; the JSON line on stdout says what happened.
Stop a run with Ctrl-C. A pull request is opened only when `npm run verify` and the
guardrail check both pass. If verify still fails after the retries but the guardrail
passes, the work in progress is pushed to its `agent/issue-N-…` branch for inspection,
and no pull request is opened.

## Serve
`python -m loop_agent serve --port 8080` accepts one job over HTTP (`POST /jobs` with
`{"repo", "issue", "sha"}`) and exits once that job has finished. That is the production
model: one container (one MicroVM) per task, so nothing one job leaves behind reaches
the next. Start a fresh container for every job.

## Tests
`cd agent && uv run pytest -q`
