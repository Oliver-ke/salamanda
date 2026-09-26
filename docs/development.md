# Development

## Repository layout

| Path | What it is | Agent may change it? |
|---|---|---|
| `app/` | The expense tracker (Next.js App Router, TypeScript, Vitest) | yes: `app/src/**` |
| `agent/` | The worker and the AWS Lambdas (Python, `uv`) | no |
| `harness/` | `@loop/harness`: the `pr-rules` guardrail CI runs (zero-dependency Node ESM) | no |
| `infra/` | Terraform for the AWS side (human-applied) | no |
| `.github/` | CI (`ci.yml`), wake-ups (`wake.yml`), branch protection | no |
| `docs/` | These documents | — |
| `CLAUDE.md` | The rules the agent follows on every run | no |

## Checks

| Command | What it runs |
|---|---|
| `npm run verify` | Typecheck, lint, tests (harness + app), build: the agent's definition of done |
| `npm run test:harness` | The guardrail tests (`node --test`) |
| `cd agent && uv run pytest -q` | The worker and Lambda tests |
| `terraform -chdir=infra fmt -check -recursive && terraform -chdir=infra validate` | Terraform formatting and validity |
| `PR_BODY="Closes #1" npm run pr:check -- --author <login>` | The PR guardrail against the current branch |

CI (`.github/workflows/ci.yml`) runs four jobs on every pull request:

| Job | Runs | Required for merge? |
|---|---|---|
| `verify` | `npm run verify` | yes |
| `pr-rules` | The guardrail, from the base branch's `harness/` | yes |
| `agent` | `pytest` in `agent/` | yes |
| `infra` | `terraform fmt -check`, `init -backend=false`, `validate` | not yet |

Required checks must never be skipped. The CI file explains why jobs have no `if:` or path filters.

## Working on the repository

- **Branch off `main`** and open a pull request. Direct pushes to `main` are blocked.
- **Humans may change protected paths.** `pr-rules` enforces them only for bot authors.
- **Never use the `agent/` branch prefix.** The worker owns it.
- **Write tests first.** The Python and harness code are fully unit-tested against fakes; only thin AWS wiring
  is exempt, and it's marked `# pragma: no cover - AWS wiring`.
- **Keep `strands` out of Lambda code.** Code under `agent/src/loop_agent/aws/` must not import it.

## Running the worker locally

Handy for trying a change on a real issue before deploying.

```bash
docker build -f agent/Dockerfile -t loop-worker .
docker run --rm --init \
  --env-file ~/.config/loop-sdlc/worker.env \
  -v ~/.config/loop-sdlc/app.pem:/run/secrets/app.pem:ro \
  -v ~/.config/loop-sdlc/anthropic.key:/run/secrets/anthropic.key:ro \
  loop-worker /opt/agent-venv/bin/python -m loop_agent run --issue <N>
```

- The image clones the repository's `main` at build time, and the run fetches `main` again at the start.
- Exit code 0 means a PR was opened. The JSON line on stdout says what happened.
- `agent/README.md` has the full local setup, including an example `worker.env`.

## Changing the loop

| Change | Where | Deploy |
|---|---|---|
| Agent behaviour or prompt | `agent/prompt.md`, `agent/src/loop_agent/` | Rebuild the image |
| Rules the agent follows | `CLAUDE.md` | None (read from the checked-out commit each run) |
| Protected paths | `harness/src/protected.mjs`, mirrored in `CLAUDE.md` and `CODEOWNERS` | None (CI reads it from `main`) |
| Scheduling, selection, run orchestration | `agent/src/loop_agent/aws/` | `package_lambdas.sh` + `terraform apply` |
| AWS resources | `infra/` | `terraform plan` / `apply` |
