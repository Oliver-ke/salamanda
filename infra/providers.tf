terraform {
  required_version = ">= 1.15"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.66"
    }
  }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile
  default_tags {
    tags = { project = "salamanda" }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name      = "salamanda"
  account   = data.aws_caller_identity.current.account_id
  image_arn = "arn:aws:lambda:${var.region}:${local.account}:microvm-image:${var.image_name}"
}
