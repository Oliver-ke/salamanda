locals {
  secret_arns = [aws_secretsmanager_secret.anthropic_api_key.arn, aws_secretsmanager_secret.github_app_private_key.arn]
  common_env = {
    LOOP_REPO                  = var.repo
    GITHUB_APP_ID              = var.github_app_id
    GITHUB_APP_INSTALLATION_ID = var.github_installation_id
    GITHUB_KEY_SECRET_ARN      = aws_secretsmanager_secret.github_app_private_key.arn
  }
  tasks = {
    start    = { handler = "loop_agent.aws.run_task.start_handler", timeout = 60 }
    dispatch = { handler = "loop_agent.aws.run_task.dispatch_handler", timeout = 240 }
    poll     = { handler = "loop_agent.aws.run_task.poll_handler", timeout = 60 }
    finish   = { handler = "loop_agent.aws.run_task.finish_handler", timeout = 60 }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "lambda" {
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      Resource = "arn:aws:logs:${var.region}:${local.account}:*" },
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = local.secret_arns },
      { Effect = "Allow", Action = ["lambda:RunMicrovm", "lambda:GetMicrovm", "lambda:CreateMicrovmAuthToken",
      "lambda:TerminateMicrovm", "lambda:GetMicrovmImage"], Resource = "arn:aws:lambda:${var.region}:${local.account}:*" },
      { Effect = "Allow", Action = ["states:ListExecutions"], Resource = aws_sfn_state_machine.run_task.arn },
      { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.tasks.arn },
    ]
  })
}

resource "aws_lambda_function" "task" {
  for_each         = local.tasks
  function_name    = "${local.name}-${each.key}"
  role             = aws_iam_role.lambda.arn
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
  function_name    = "${local.name}-intake"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "loop_agent.aws.intake.handler"
  timeout          = 60
  memory_size      = 256
  filename         = var.lambda_zip
  source_code_hash = filebase64sha256(var.lambda_zip)
  environment {
    variables = merge(local.common_env, {
      STATE_MACHINE_ARN = aws_sfn_state_machine.run_task.arn
      QUEUE_URL         = aws_sqs_queue.tasks.url
    })
  }
}
