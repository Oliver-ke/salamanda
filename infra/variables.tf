variable "region" {
  type    = string
  default = "eu-west-1"
}

variable "aws_profile" {
  type    = string
  default = null
}

variable "repo" {
  type        = string
  description = "owner/name of the repository the loop works on"
}

variable "github_app_id" {
  type = string
}

variable "github_installation_id" {
  type = string
}

variable "image_name" {
  type    = string
  default = "salamanda-worker"
}

variable "lambda_zip" {
  type    = string
  default = "../build/lambdas.zip"
}

variable "max_run_seconds" {
  type        = number
  default     = 3900
  description = "Platform hard cap on one MicroVM (the state machine gives up after 3600 s of polling)"
}

variable "schedule_enabled" {
  type    = bool
  default = false
}

variable "schedule_expression" {
  type    = string
  default = "rate(15 minutes)"
}
