data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.intake.arn }]
  })
}

# Created DISABLED. A human enables it (schedule_enabled = true) after the first manual run succeeds.
resource "aws_scheduler_schedule" "intake" {
  name                = "${local.name}-intake"
  schedule_expression = var.schedule_expression
  state               = var.schedule_enabled ? "ENABLED" : "DISABLED"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.intake.arn
    role_arn = aws_iam_role.scheduler.arn
    # Never retry a scheduled intake: a retry after a transient failure could race a
    # fresh schedule tick and queue two issues at once.
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
