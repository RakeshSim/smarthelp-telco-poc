terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Filled in via `terraform init -backend-config=envs/<env>/backend.hcl`.
  # Kept empty here so the same root config works for dev/qa/prod.
  backend "s3" {}
}
