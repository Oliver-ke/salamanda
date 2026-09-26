# Intake's backoff record. Written by the Lambdas; Terraform only creates it.
resource "aws_ssm_parameter" "intake_backoff" {
  name  = "/${local.name}/intake-backoff"
  type  = "String"
  value = "{}"
  lifecycle {
    ignore_changes = [value]
  }
}
