data "aws_iam_policy_document" "sfn_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${local.name}-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_trust.json
}

resource "aws_iam_role_policy" "sfn" {
  role = aws_iam_role.sfn.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [for f in aws_lambda_function.task : f.arn] }]
  })
}

resource "aws_sfn_state_machine" "run_task" {
  name     = "${local.name}-run-task"
  role_arn = aws_iam_role.sfn.arn
  definition = templatefile("${path.module}/../agent/src/loop_agent/aws/state_machine.asl.json", {
    start_arn    = aws_lambda_function.task["start"].arn
    dispatch_arn = aws_lambda_function.task["dispatch"].arn
    poll_arn     = aws_lambda_function.task["poll"].arn
    finish_arn   = aws_lambda_function.task["finish"].arn
  })
}
