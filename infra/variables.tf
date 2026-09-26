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
  default     = 4500
  description = "Platform hard cap on one MicroVM (the state machine gives up after 3600 s of polling, plus start, dispatch and finish)"
}

variable "intake_reserved_concurrency" {
  type        = number
  default     = 1
  nullable    = true
  description = "Reserved concurrency for the intake Lambda. null skips it (needed while the account's concurrency limit is 10: Lambda keeps 10 unreserved). One run at a time still holds through the labels and the running-execution check."
}

variable "schedule_enabled" {
  type    = bool
  default = false
}

variable "schedule_expression" {
  type    = string
  default = "rate(15 minutes)"
}
