resource "aws_sqs_queue" "dead_letter" {
  name       = "${local.name}-tasks-dlq.fifo"
  fifo_queue = true
}

resource "aws_sqs_queue" "tasks" {
  name                       = "${local.name}-tasks.fifo"
  fifo_queue                 = true
  visibility_timeout_seconds = 60
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 3
  })
}

# No actions: check it in CloudWatch (the runbook says when). A message here means a job
# the Pipe could not start three times.
resource "aws_cloudwatch_metric_alarm" "dead_letter_not_empty" {
  alarm_name          = "${local.name}-tasks-dlq-not-empty"
  alarm_description   = "Jobs the Pipe could not start: see infra/README.md"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dead_letter.name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
}
