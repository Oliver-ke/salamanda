# infra

Terraform for the AWS side of the loop: EventBridge Scheduler, SQS, Step Functions,
the intake and bug-finder Lambdas, the worker's Lambda MicroVM image, IAM and secrets.
Built in Plan 2.

Terraform is human-only. CI runs `fmt -check`, `validate` and `plan` with read-only
credentials; a human runs `apply`. The agent never touches this directory:
`harness/src/protected.mjs` lists `infra/`, and `pr-rules` fails any bot pull request
that changes it.
