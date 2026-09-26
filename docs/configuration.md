# Configuration

## Worker environment

These are read by `loop_agent/config.py`. In the MicroVM, the non-secret ones are set on the image, and the
secrets arrive with each job. Locally, they come from `~/.config/loop-sdlc/worker.env`.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `LOOP_REPO` | yes | — | `owner/name` of the repository to work on |
| `LOOP_REPO_DIR` | yes | `/workspace/repo` (image) | Checkout the worker operates on |
| `GITHUB_APP_ID` | yes | — | The GitHub App's ID |
| `GITHUB_APP_INSTALLATION_ID` | yes | — | Installation ID on the repository |
| `GITHUB_APP_PRIVATE_KEY` or `…_FILE` | yes | — | App private key, inline or from a `chmod 600` file (sent with each job in the MicroVM) |
| `LOOP_BOT_LOGIN` | yes | — | The bot's login, ending in `[bot]`, e.g. `salamanda-loop[bot]` |
| `LOOP_GIT_AUTHOR_EMAIL` | yes | — | `<bot-user-id>+<app-slug>[bot]@users.noreply.github.com` |
| `LOOP_MODEL_PROVIDER` | no | `anthropic` | `anthropic` or `bedrock` |
| `LOOP_MODEL_ID` | no | `claude-opus-5-5` | Model, for the Anthropic provider |
| `LOOP_EFFORT` | no | `high` | `low`, `medium`, `high`, `xhigh` or `max` (Opus 5.5 would otherwise default to `medium`) |
| `ANTHROPIC_API_KEY` or `…_FILE` | for `anthropic` | — | API key (sent with each job in the MicroVM) |
| `BEDROCK_MODEL_ID`, `AWS_REGION` | for `bedrock` | — | Bedrock inference profile and region |
| `LOOP_MAX_TOOL_CALLS` | no | `60` | Tool-call budget per run |
| `LOOP_COMMAND_USER` | no | `runner` (image) | Unprivileged user for agent-run commands |
| `LOOP_SNAPSHOT_LOCK_FILE` | no | set by the image | Lockfile hash from the image build; `npm ci` runs only if it differs |

## Lambda environment

Terraform sets these. They're listed for reference only.

| Variable | Lambdas | Meaning |
|---|---|---|
| `LOOP_REPO`, `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_KEY_SECRET_ARN` | all | GitHub access |
| `ANTHROPIC_SECRET_ARN`, `IMAGE_ARN`, `MAX_RUN_SECONDS` | task | Dispatching and running MicroVMs |
| `STATE_MACHINE_ARN`, `QUEUE_URL` | intake | Checking in-flight runs and queuing |
| `BACKOFF_PARAMETER`, `INTAKE_BASE_SECONDS` | intake, task | The backoff record |
| `INTAKE_SLEEP_SECONDS`, `LOOP_ENABLED` | intake | The idle ceiling, and the kill switch (mirrors `schedule_enabled`) |

## Terraform variables

These live in `infra/variables.tf`. Set yours in `infra/local.tfvars`, which is gitignored, starting from
`infra/example.tfvars`.

| Variable | Default | Meaning |
|---|---|---|
| `repo` | — | `owner/name` |
| `github_app_id`, `github_installation_id` | — | The GitHub App |
| `region` | `eu-west-1` | AWS region |
| `aws_profile` | `null` | AWS CLI profile |
| `image_name` | `salamanda-worker` | MicroVM image name |
| `lambda_zip` | `../build/lambdas.zip` | Lambda package from `package_lambdas.sh` |
| `max_run_seconds` | `4500` | Platform hard cap on one MicroVM |
| `schedule_enabled` | `false` | The loop's on/off switch: the schedule and wake-ups |
| `schedule_expression` | `rate(2 minutes)` | Intake tick |
| `intake_base_seconds` | `120` | Shortest wait between checks; keep equal to the tick |
| `intake_sleep_minutes` | `32` | Longest wait while idle (reached after 4 idle ticks) |
| `intake_reserved_concurrency` | `1` | `null` while the account's Lambda concurrency limit is 10 |
| `github_oidc_provider_arn` | `null` | Reuse an existing GitHub OIDC provider (one per account) |
| `github_oidc_sub_prefix` | `null` → `repo:<owner>/<repo>` | For repos with immutable OIDC subjects: `repo:<owner>@<id>/<repo>@<id>` (from `gh api repos/<owner>/<repo>/actions/oidc/customization/sub`) |

## Repository variables (GitHub)

| Variable | Meaning |
|---|---|
| `AWS_WAKE_ROLE_ARN` | The wake role, from the Terraform output `wake_role_arn`. When unset, the wake workflow is skipped. |

## Labels

Create these once with `gh label create`:

| Label | Colour |
|---|---|
| `agent:ready` | `0E8A16` |
| `agent:queued` | `FBCA04` |
| `agent:running` | `1D76DB` |
| `agent:failed` | `D93F0B` |
| `agent:too-big` | `5319E7` |
| `priority:high` | `B60205` |
| `priority:low` | `C2E0C6` |

`agent:requeued` is created automatically the first time it is used.
