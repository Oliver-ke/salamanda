data "aws_iam_policy_document" "pipes_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["pipes.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pipes" {
  name               = "${local.name}-pipes"
  assume_role_policy = data.aws_iam_policy_document.pipes_trust.json
}

resource "aws_iam_role_policy" "pipes" {
  role = aws_iam_role.pipes.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
      Resource = aws_sqs_queue.tasks.arn },
      { Effect = "Allow", Action = ["states:StartExecution"], Resource = aws_sfn_state_machine.run_task.arn },
    ]
  })
}

resource "aws_pipes_pipe" "tasks" {
  name     = "${local.name}-tasks"
  role_arn = aws_iam_role.pipes.arn
  source   = aws_sqs_queue.tasks.arn
  target   = aws_sfn_state_machine.run_task.arn
  source_parameters {
    sqs_queue_parameters {
      batch_size = 1
    }
  }
  target_parameters {
    input_template = "{\"repo\": \"<$.body.repo>\", \"issue\": <$.body.issue>, \"sha\": \"<$.body.sha>\"}"
    step_function_state_machine_parameters {
      invocation_type = "FIRE_AND_FORGET"
    }
  }
}
