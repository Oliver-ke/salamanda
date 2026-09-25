# loop-sdlc

A closed loop that builds an app: a GitHub issue goes in, an AI agent in an isolated
Lambda MicroVM does it, a pull request comes out, a human merges. Repeat.

Design: `docs/superpowers/specs/2026-09-25-lambda-microvm-loop-design.md`.

## Layout
| Path | What it is |
|---|---|
| `app/` | The expense tracker — the Next.js app the agent builds |
| `agent/` | The worker: Strands agent on Bedrock, its tool sandbox, and the code that opens the PR (Python) |
| `harness/` | `@loop/harness`: the `pr-rules` guardrail CI runs on every pull request |
| `infra/` | Terraform for the AWS side. Humans only: CI plans, a human applies |

## The loop
1. A human writes an issue and labels it `agent:ready`. That label is the approval.
2. On a schedule, the intake Lambda queues the next eligible issue.
3. A Step Functions run starts a MicroVM, the worker does the issue, and the MicroVM
   is always terminated.
4. On success the worker opens a pull request with `Closes #N`. On failure it comments
   on the issue and opens nothing.
5. A human reviews and merges. Nothing merges without `verify`, `pr-rules` and `agent` green.

(Steps 2–3 land in Plan 2. Until then the worker runs locally — see `agent/README.md`.)

## Commands
| Command | What it does |
|---|---|
| `npm run verify` | typecheck, lint, test, build — the definition of done |
| `PR_BODY="Closes #1" npm run pr:check -- --author <login>` | runs the PR guardrails against the current branch |

## Reviewing an agent pull request
Read the diff, then confirm it does what the issue asked. Two specific traps:

- **A pull request showing *no* checks at all is itself the red flag.** A change that
  breaks a workflow file's YAML stops it parsing, so no check runs get posted and
  required checks stay pending. Never admin-merge a pull request with missing or
  pending checks.
- **`verify` cannot see a weakened test.** The agent may write unit tests under
  `app/src/`, so it can also weaken its own. Only `app/tests/acceptance/` is beyond its
  reach. Until those exist, human review is the only thing catching a deleted assertion.

## What the agent may not change
`.github/`, `infra/`, `harness/`, `agent/`, `app/tests/acceptance/`, `CLAUDE.md`,
`CODEOWNERS`, `app/CLAUDE.md`, `app/AGENTS.md`, `package.json`, `package-lock.json`,
`app/package.json`, `app/tsconfig.json`, `.nvmrc`, plus every extension of
`app/vitest.config.*`, `app/vitest.setup.*`, `app/eslint.config.*`,
`app/next.config.*` and `app/postcss.config.*`. **`harness/src/protected.mjs` is the
authoritative list**; this paragraph and `CODEOWNERS` mirror it. It is enforced three
times:

1. **The worker's file tools** refuse these paths. This is defence in depth, not the
   boundary.
2. **The required `pr-rules` check** fails any bot pull request that touches one.
   - The check also fails a bot PR that doesn't close exactly one issue.
   - Config families are protected by stem, so an agent can't *add* a second config
     that shadows a protected one.
   - The diff runs with `--no-renames`, so moving a protected file counts as touching it.
   - CI runs the checker from the **base** branch (`git archive`), so a pull request
     can't supply its own judge.
3. **The worker's GitHub App has no `workflows` permission,** so GitHub itself rejects
   any bot push touching `.github/workflows/`. That closes the hole `pr-rules` alone
   can't: a pull request editing `ci.yml` to make its own check pass.

## Stopping it
Plan 2 adds the AWS kill switches (disable the schedule, stop the Step Functions
execution). Today, and always:

```bash
# Suspend the GitHub App installation (Settings → Integrations → GitHub Apps),
# or delete its private key — every run then fails closed.
```
