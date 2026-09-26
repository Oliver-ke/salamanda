# infra

Terraform for the AWS side of the loop (eu-west-1): the intake Lambda on a schedule, the SQS FIFO
queue and its dead-letter queue, an EventBridge Pipe into the `run-task` Step Functions state
machine, its four task Lambdas, the image build role and artifact bucket, and two Secrets Manager
secrets. The MicroVM image itself is built by `agent/deploy/build_image.py`, because Terraform
can't set its `/ready` hook.

Terraform is human-only. CI runs `fmt -check` and `validate`; a human runs `plan` and `apply`.
The agent never touches this directory.

## First deploy
Before the first apply, check the account's unreserved concurrency:
`aws --profile veroak lambda get-account-settings --query AccountLimit.UnreservedConcurrentExecutions`.
If it is 10 or less, the intake's `reserved_concurrent_executions = 1` will fail to apply
(Lambda keeps 10 unreserved). Request a concurrency increase, or temporarily remove that line.

```bash
agent/deploy/package_lambdas.sh                                  # build/lambdas.zip
cp infra/example.tfvars infra/local.tfvars                       # edit if needed; not committed
terraform -chdir=infra init
terraform -chdir=infra apply -var-file=local.tfvars              # schedule stays DISABLED

# Secrets (read from files, never on the command line, never through Terraform or git)
aws --profile veroak secretsmanager put-secret-value --secret-id "$(terraform -chdir=infra output -raw anthropic_secret_arn)" \
  --secret-string file://$HOME/.config/loop-sdlc/anthropic.key
aws --profile veroak secretsmanager put-secret-value --secret-id "$(terraform -chdir=infra output -raw github_key_secret_arn)" \
  --secret-string file://$HOME/.config/loop-sdlc/app.pem

# Image: non-secret settings only
grep -vE '^(ANTHROPIC_API_KEY|GITHUB_APP_PRIVATE_KEY)' ~/.config/loop-sdlc/worker.env > /tmp/image.env
(cd agent && uv run python -m deploy.build_image --profile veroak \
  --bucket "$(terraform -chdir=../infra output -raw artifact_bucket)" \
  --build-role-arn "$(terraform -chdir=../infra output -raw build_role_arn)" --env-file /tmp/image.env)
```

## First run, by hand
Send the job through the queue, as intake would, so the Pipe is exercised with someone watching.
Label the issue `agent:queued` first (`gh issue edit <N> --add-label agent:queued --remove-label agent:ready`),
as intake would.
```bash
SHA=$(gh api repos/Oliver-ke/salamanda/branches/main --jq .commit.sha)
aws --profile veroak sqs send-message --queue-url "$(terraform -chdir=infra output -raw queue_url)" \
  --message-group-id Oliver-ke/salamanda --message-deduplication-id "<N>-$SHA" \
  --message-body "{\"repo\":\"Oliver-ke/salamanda\",\"issue\":<N>,\"sha\":\"$SHA\"}"
```
Fallback, if the Pipe is the problem (skips the queue entirely):
```bash
aws --profile veroak stepfunctions start-execution \
  --state-machine-arn "$(terraform -chdir=infra output -raw state_machine_arn)" \
  --input "{\"repo\":\"Oliver-ke/salamanda\",\"issue\":<N>,\"sha\":\"$SHA\"}"
```
Watch it in the Step Functions console. Expect a PR (or an issue comment) and a terminated MicroVM.

Before enabling the schedule, check the `salamanda-tasks-dlq-not-empty` alarm in CloudWatch: it must be
`OK` (a message in the dead-letter queue is a job the Pipe could not start). The alarm has no actions,
so keep checking it by hand while the loop runs.
Then turn the loop on: `terraform -chdir=infra apply -var-file=local.tfvars -var schedule_enabled=true`.

## Stopping it (any one is enough)
| Stop | Command |
|---|---|
| No new runs | `terraform -chdir=infra apply -var-file=local.tfvars -var schedule_enabled=false` (or disable the schedule in the console) |
| The run in flight | `aws stepfunctions stop-execution --execution-arn <arn>` (then `aws lambda-microvms terminate-microvm` if it was mid-run: stopping skips the finish step) |
| Everything, hard | Suspend the GitHub App installation, or revoke the Anthropic key: every run then fails closed |

## Where the caps are
| Cap | Where |
|---|---|
| One intake at a time | intake Lambda reserved concurrency 1; the schedule never retries |
| One run at a time | intake refuses while an execution runs or an issue is `agent:queued`/`agent:running` |
| Wall clock per run | 120 polls × 30 s in the state machine; `max_run_seconds` (4500 s) on the MicroVM itself |
| Tool calls per run | `LOOP_MAX_TOOL_CALLS` (default 60) in the image env |
| Model spend | the Anthropic Console spend limit on the key's workspace |
