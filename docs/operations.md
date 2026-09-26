# Operations

Commands assume the AWS profile `veroak`, region `eu-west-1`, and the repository root as the working
directory. `infra/README.md` has the same runbook in its shortest form.

## Prerequisites (one time)

1. **The GitHub App `salamanda-loop`:**
   - installed on the repository, with the permissions in [Security](security.md#the-bots-identity);
   - its private key saved outside the repo with `chmod 600`, e.g. `~/.config/loop-sdlc/app.pem`.
2. **An Anthropic API key** with credit, saved to `~/.config/loop-sdlc/anthropic.key` with `chmod 600`.
3. **The loop's labels on the repository.** See [Configuration](configuration.md#labels).
4. **Tools:** Terraform ≥ 1.15, `uv`, the AWS CLI, `gh`, Docker for local runs.
5. **Account limits.** A new AWS account may have a Lambda concurrency limit of 10. If
   `aws lambda get-account-settings` shows 10 or fewer unreserved executions, set
   `intake_reserved_concurrency = null` in `infra/local.tfvars` until an increase is granted.

## Deploy

```bash
agent/deploy/package_lambdas.sh                         # build/lambdas.zip (arm64, Python 3.13)
cp infra/example.tfvars infra/local.tfvars              # then edit; gitignored
terraform -chdir=infra init
terraform -chdir=infra plan -var-file=local.tfvars -out=tfplan
terraform -chdir=infra apply tfplan                     # the schedule starts disabled
```

**Secret values** are read from files, never typed on the command line:

```bash
aws secretsmanager put-secret-value --secret-id "$(terraform -chdir=infra output -raw anthropic_secret_arn)" \
  --secret-string file://$HOME/.config/loop-sdlc/anthropic.key
aws secretsmanager put-secret-value --secret-id "$(terraform -chdir=infra output -raw github_key_secret_arn)" \
  --secret-string file://$HOME/.config/loop-sdlc/app.pem
```

**The worker image** takes non-secret settings only:

```bash
grep -vE '^(ANTHROPIC_API_KEY|GITHUB_APP_PRIVATE_KEY)' ~/.config/loop-sdlc/worker.env > /tmp/image.env
(cd agent && uv run python -m deploy.build_image --profile veroak \
  --bucket "$(terraform -chdir=../infra output -raw artifact_bucket)" \
  --build-role-arn "$(terraform -chdir=../infra output -raw build_role_arn)" --env-file /tmp/image.env)
```

**Wake-ups** need the role ARN set as a repository variable:

```bash
gh variable set AWS_WAKE_ROLE_ARN -R Oliver-ke/salamanda --body "$(terraform -chdir=infra output -raw wake_role_arn)"
```

If the account already has a GitHub OIDC provider, set `github_oidc_provider_arn`. If the repository uses
immutable OIDC subjects, set `github_oidc_sub_prefix`. See [Configuration](configuration.md#terraform-variables).

**Redeploy after changing code:**
- Worker changes (`agent/src/loop_agent/` outside `aws/`, `agent/prompt.md`, the Dockerfile): rebuild the image.
- Lambda changes (`agent/src/loop_agent/aws/`, `gitops.py`, `github.py`): re-run `package_lambdas.sh`, then
  `plan` and `apply`.
- When both change, redeploy both together.

## Run

**The first run** goes through the queue, as intake would do it:

```bash
SHA=$(gh api repos/Oliver-ke/salamanda/branches/main --jq .commit.sha)
gh issue edit <N> -R Oliver-ke/salamanda --add-label agent:queued --remove-label agent:ready
aws sqs send-message --queue-url "$(terraform -chdir=infra output -raw queue_url)" \
  --message-group-id Oliver-ke/salamanda --message-deduplication-id "<N>-$SHA" \
  --message-body "{\"repo\":\"Oliver-ke/salamanda\",\"issue\":<N>,\"sha\":\"$SHA\"}"
```

Watch the execution in the Step Functions console, under `salamanda-run-task`.

**Turn the loop on** by setting `schedule_enabled = true` in `local.tfvars`, then `apply`. From then on:
- intake checks every 2 minutes, backing off to 32 minutes while idle;
- `agent:ready` labels, merges to `main` and finished runs wake it straight away.

## Stop

Any one of these is enough:

| Stop | How | Effect |
|---|---|---|
| No new runs | `schedule_enabled = false`, then `apply` | Disables the schedule, **and** intake ignores wake-ups |
| Wake-ups only | `gh variable delete AWS_WAKE_ROLE_ARN -R Oliver-ke/salamanda` | Polling continues |
| The run in flight | `aws stepfunctions stop-execution --execution-arn <arn>` | Stopping skips Finish, so also run `aws lambda-microvms terminate-microvm` and clear the issue's labels |
| Everything, hard | Suspend the GitHub App installation, or revoke the Anthropic key | Every run fails closed |

Disabling only the schedule in the AWS console leaves wake-ups working. Use Terraform.

## Caps

| Cap | Where |
|---|---|
| One run at a time | Intake refuses while any execution runs or any issue is `agent:queued`/`agent:running` |
| One intake at a time | Reserved concurrency 1 (`intake_reserved_concurrency`); no retries |
| Wall clock per run | 120 polls × 30 s in the state machine; `max_run_seconds` (4500 s) on the MicroVM |
| Tool calls per run | `LOOP_MAX_TOOL_CALLS` (60) |
| Child issues per run | 5 |
| Model spend | The Anthropic Console spend limit on the key's workspace |

## Observe

| What | Where |
|---|---|
| Intake decisions (queued issue, skip reasons, backoff) | CloudWatch Logs `/aws/lambda/salamanda-intake` |
| Each run's steps and payloads | Step Functions console → `salamanda-run-task` → executions |
| Task Lambda errors | CloudWatch Logs `/aws/lambda/salamanda-{start,dispatch,poll,finish}` |
| Jobs that couldn't start | Dead-letter queue `salamanda-tasks-dlq.fifo`, and the alarm `salamanda-tasks-dlq-not-empty` |
| Backoff state | `aws ssm get-parameter --name /salamanda/intake-backoff` |
| Wake-ups | GitHub → Actions → "Wake the loop" |
| Live MicroVMs | `lambda-microvms list-microvms` (boto3 ≥ 1.43; older AWS CLIs lack the command) |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Issue gets `agent:failed`: "credit balance is too low" | The Anthropic key's workspace is out of credit | Add credit, then re-add `agent:ready` |
| Start fails: `not authorized to perform: lambda:PassNetworkConnector` | Task role missing connector permission | Present since PR #13; re-apply Terraform |
| Wake workflow: "Not authorized to perform sts:AssumeRoleWithWebIdentity" | The OIDC subject doesn't match the trust | Set `github_oidc_sub_prefix` (immutable subjects), then apply |
| Nothing starts after a merge | Remaining issues depend on still-open issues, or are `agent:failed` | Check the intake log's `reasons`; re-add `agent:ready` to failed issues |
| An issue stuck at `agent:queued` | The run never started (the Pipe or a Lambda failed) | Intake requeues it once, then marks it failed; check the dead-letter queue and Step Functions |
| `terraform apply` fails on intake with a concurrency error | Account concurrency limit is 10 | `intake_reserved_concurrency = null` |
| Image build `CREATE_FAILED` | Dockerfile or build error | `ListMicrovmImageVersions` → `stateReason`, and CloudWatch `/aws/lambda-microvms/salamanda-worker` |
