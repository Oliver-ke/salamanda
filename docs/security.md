# Security and guardrails

The loop executes code written by an AI, driven by text written by whoever can open an issue.
The guardrails assume either could be wrong or hostile, and they are layered, so no single one has to be perfect.

## Approval gates

- **Nothing runs without `agent:ready`.** Only people who can label issues (collaborators) can approve work.
- **Nothing merges without a human.** `main` is protected:
  - pull requests only, with admins included;
  - linear history, no force pushes;
  - the required checks `verify`, `pr-rules` and `agent` must pass.

## Protected paths

The agent may not change these. `harness/src/protected.mjs` is the authoritative list:

`.github/`, `infra/`, `harness/`, `agent/`, `app/tests/acceptance/`, `CLAUDE.md`, `CODEOWNERS`,
`app/CLAUDE.md`, `app/AGENTS.md`, `package.json`, `package-lock.json`, `app/package.json`,
`app/tsconfig.json`, `.nvmrc`, and every extension of `app/vitest.config.*`, `app/vitest.setup.*`,
`app/eslint.config.*`, `app/next.config.*` and `app/postcss.config.*`.

Three layers enforce it:
1. **The agent's file tools** refuse protected paths. This is defence in depth.
2. **The required `pr-rules` check** fails any bot PR that touches one.
   - Config families are protected by stem, so a *new* `vitest.config.ts` can't shadow the protected one.
   - The diff runs with `--no-renames`, so moving a protected file counts as touching it.
   - CI runs the checker from the **base** branch, so a PR can't supply its own judge.
   - The check also requires exactly one `Closes #N` in a bot PR.
3. **The GitHub App has no `workflows` permission**, so GitHub itself rejects any bot push touching
   `.github/workflows/`. This closes the one gap an in-repo check can't: a PR editing CI to pass itself.

## The bot's identity

The GitHub App `salamanda-loop` is installed on this repository only:

| Permission | Access |
|---|---|
| Contents | read/write |
| Issues | read/write |
| Pull requests | read/write |
| Metadata | read |
| Workflows | **none** |

## Inside the MicroVM

- **One MicroVM per run**, terminated at the end. Nothing carries over between runs.
- **No AWS role.** The MicroVM has no execution role, so a process reading the metadata endpoint gets no
  credentials. The worker needs only GitHub and Anthropic.
- **Two users.**
  - The worker runs as root and holds the secrets.
  - Everything the agent triggers, such as tests and builds, runs as the unprivileged `runner` user with
    `AWS_*`, `GITHUB_APP_*`, `BEDROCK_*`, `LOOP_*` and `ANTHROPIC_*` removed from its environment.
    `runner` can't read root's process memory or environment.
- **`.git` belongs to root.**
  - The agent can't plant git hooks or config.
  - The worker runs git with hooks and fsmonitor disabled.
  - The worker refuses to run git at all if `.git` has been swapped or made writable by others.
- **Credentials stay out of argv.** The GitHub token goes to `git push` through the environment, never the
  command line, which any process can read.
- **Nothing outlives its command.** After every agent command, the worker kills the command's process group
  *and* every process owned by `runner`. That includes detached ones that escaped the group.

## Secrets

| Secret | Stored in | Read by |
|---|---|---|
| Anthropic API key | Secrets Manager `salamanda/anthropic-api-key` | the dispatch Lambda, which sends it to the MicroVM with the job |
| GitHub App private key | Secrets Manager `salamanda/github-app-private-key` | intake and the task Lambdas; the MicroVM gets it with the job |

- **Never in the image.** The image build refuses secret-looking settings, and builds the image from
  git-tracked files only.
- **Never in logs, Step Functions payloads, `/jobs/current`, or issue comments.** Comments are scrubbed of
  secret values and of credentials in URLs.
- **Set by a human** with `aws secretsmanager put-secret-value --secret-string file://…`, so the value never
  appears on a command line.

## AWS access

- **Split roles.**
  - Intake can read the GitHub key, list executions, send to the queue, and use the backoff parameter.
  - The task Lambdas can read both secrets and run, poll and terminate MicroVMs.
  - No role has `iam:PassRole`.
- **The wake role** can only invoke intake. Only a GitHub Actions workflow running on this repository's `main`
  can assume it; the trust uses the repository's immutable OIDC subject.
- **Terraform is human-only.** CI runs `fmt` and `validate`; a human runs `plan` and `apply`.

## Known limits

- **`verify` can't see a weakened test.** The agent writes unit tests under `app/src/`, so it could weaken
  its own. Human review, and future human-written acceptance tests in `app/tests/acceptance/`, catch that.
- **Egress is open.** Agent-run tests have internet access. They have no credentials to leak, but they could
  make outbound requests.
- **Issue text reaches the model.** It is framed as requirements, but prompt injection through an issue is
  mitigated by the approval gate and the guardrails above, not prevented.
