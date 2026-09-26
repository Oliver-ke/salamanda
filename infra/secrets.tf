# Values are set by a human with `aws secretsmanager put-secret-value`; never in Terraform.
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name = "${local.name}/anthropic-api-key"
}

resource "aws_secretsmanager_secret" "github_app_private_key" {
  name = "${local.name}/github-app-private-key"
}
