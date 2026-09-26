locals {
  secret_arns = [aws_secretsmanager_secret.anthropic_api_key.arn, aws_secretsmanager_secret.github_app_private_key.arn]
  common_env = {
    LOOP_REPO                  = var.repo
    GITHUB_APP_ID              = var.github_app_id
    GITHUB_APP_INSTALLATION_ID = var.github_installation_id
    GITHUB_KEY_SECRET_ARN      = aws_secretsmanager_secret.github_app_private_key.arn
  }
  tasks = {
    start = { handler = "loop_agent.aws.run_task.start_handler", timeout = 60 }
    # Worst case for dispatch: MicroVM.wait_running's default timeout_s (120 s, see
    # agent/src/loop_agent/aws/microvm.py) + HEALTH_ATTEMPTS x (5 s /health request +
    # 2 s sleep) = 30 x 7 s = 210 s (agent/src/loop_agent/aws/run_task.py) + the POST
    # /jobs call's default http_json timeout (30 s, microvm.py) = 360 s worst case.
    # timeout is set to 420 s to leave headroom above that budget.
    dispatch = { handler = "loop_agent.aws.run_task.dispatch_handler", timeout = 420 }
    poll     = { handler = "loop_agent.aws.run_task.poll_handler", timeout = 60 }
    finish   = { handler = "loop_agent.aws.run_task.finish_handler", timeout = 60 }
  }
}

# Intake only reads GitHub issues/PRs, checks in-flight Step Functions executions and
# enqueues one SQS message: it never touches the MicroVM Lambda actions or the
# Anthropic key, so it gets its own, narrower role.
resource "aws_iam_role" "intake" {
  name               = "${local.name}-intake"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "intake" {
  role = aws_iam_role.intake.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      Resource = "arn:aws:logs:${var.region}:${local.account}:*" },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = aws_secretsmanager_secret.github_app_private_key.arn },
      { Effect = "Allow", Action = ["states:ListExecutions"], Resource = aws_sfn_state_machine.run_task.arn },
      { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.tasks.arn },
    ]
  })
}

# The four task Lambdas (start/dispatch/poll/finish): they drive the MicroVM and need
# both secrets (GitHub to comment/label, Anthropic to hand to the worker), but never
# touch Step Functions or SQS themselves.
resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "task" {
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      Resource = "arn:aws:logs:${var.region}:${local.account}:*" },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = local.secret_arns },
      # RunMicrovm may also authorise the AWS-owned ingress/egress network connectors.
      { Effect = "Allow", Action = ["lambda:RunMicrovm", "lambda:GetMicrovm", "lambda:CreateMicrovmAuthToken",
        "lambda:TerminateMicrovm", "lambda:GetMicrovmImage"],
        Resource = ["arn:aws:lambda:${var.region}:${local.account}:*",
      "arn:aws:lambda:${var.region}:aws:network-connector:*"] },
    ]
  })
}

resource "aws_lambda_function" "task" {
  for_each         = local.tasks
  function_name    = "${local.name}-${each.key}"
  role             = aws_iam_role.task.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = each.value.handler
  timeout          = each.value.timeout
  memory_size      = 256
  filename         = var.lambda_zip
  source_code_hash = filebase64sha256(var.lambda_zip)
  environment {
    variables = merge(local.common_env, {
      IMAGE_ARN            = local.image_arn
      MAX_RUN_SECONDS      = tostring(var.max_run_seconds)
      ANTHROPIC_SECRET_ARN = aws_secretsmanager_secret.anthropic_api_key.arn
    })
  }
}

resource "aws_lambda_function" "intake" {
  function_name = "${local.name}-intake"
  role          = aws_iam_role.intake.arn
  runtime       = "python3.13"
  architectures = ["arm64"]
  handler       = "loop_agent.aws.intake.handler"
  timeout       = 60
  memory_size   = 256
  # Never let two intakes race and queue two issues: only one concurrent execution.
  # null skips the reservation on accounts whose concurrency limit is still 10.
  reserved_concurrent_executions = var.intake_reserved_concurrency
  filename                       = var.lambda_zip
  source_code_hash               = filebase64sha256(var.lambda_zip)
  environment {
    variables = merge(local.common_env, {
      STATE_MACHINE_ARN = aws_sfn_state_machine.run_task.arn
      QUEUE_URL         = aws_sqs_queue.tasks.url
    })
  }
}

# The schedule already never retries; this stops Lambda's own async retries too, so a
# failed intake is simply picked up by the next scheduled one.
resource "aws_lambda_function_event_invoke_config" "intake" {
  function_name          = aws_lambda_function.intake.function_name
  maximum_retry_attempts = 0
}
