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
