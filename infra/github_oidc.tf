# GitHub Actions wakes intake on `issues: labeled` and pushes to main (.github/workflows/wake.yml).
# The role can only invoke intake, and only a workflow run on this repo's main branch can assume it.
resource "aws_iam_openid_connect_provider" "github" {
  count          = var.github_oidc_provider_arn == null ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  github_oidc_arn = coalesce(var.github_oidc_provider_arn, one(aws_iam_openid_connect_provider.github[*].arn))
}

data "aws_iam_policy_document" "wake_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "wake" {
  name               = "${local.name}-wake"
  assume_role_policy = data.aws_iam_policy_document.wake_trust.json
}

resource "aws_iam_role_policy" "wake" {
  role = aws_iam_role.wake.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = aws_lambda_function.intake.arn }]
  })
}
