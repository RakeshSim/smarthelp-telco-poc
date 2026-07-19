variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment stage: dev, qa, or prod."
  type        = string
  validation {
    condition     = contains(["dev", "qa", "prod"], var.environment)
    error_message = "environment must be one of: dev, qa, prod."
  }
}

variable "project_name" {
  description = "Short project name, used as a prefix for resource names."
  type        = string
  default     = "telco-support"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for Lambda log groups."
  type        = number
  default     = 14
}

variable "max_diagnostic_attempts" {
  description = <<-EOT
    Written to SSM Parameter Store and read by the starter Lambda at
    runtime (demonstrates reading runtime config from a config store,
    not just baking it into Lambda env vars). Caps how many
    diagnose/act loops run before the workflow escalates to a
    technician dispatch instead of retrying forever.
  EOT
  type        = number
  default     = 2
}

variable "approver_email" {
  description = "Optional email to subscribe to the ops-approval SNS topic (requires clicking a confirmation link AWS emails you). Leave empty to review/approve pending cases via the AWS CLI or Step Functions console instead."
  type        = string
  default     = ""
}

variable "customer_notification_email" {
  description = "Optional email to subscribe to the customer-notifications SNS topic, simulating the customer-facing channel. Leave empty to skip."
  type        = string
  default     = ""
}

variable "reaper_schedule_expression" {
  description = "EventBridge schedule expression that triggers the reaper Lambda."
  type        = string
  default     = "rate(15 minutes)"
}

variable "reaper_stale_after_minutes" {
  description = "How long a session can sit in IN_PROGRESS/PENDING_APPROVAL before the reaper considers it for reconciliation."
  type        = number
  default     = 15
}

variable "analytics_retention_days" {
  description = "S3 lifecycle expiration for analytics records — keeps the demo dataset from growing (and costing) indefinitely."
  type        = number
  default     = 30
}

variable "github_oidc_subject_prefix" {
  description = <<-EOT
    The fixed part of this repo's GitHub Actions OIDC `sub` claim, used to
    scope the trust policies in cicd.tf. GitHub's current format embeds
    the numeric owner/repo IDs, not just their names —
    repo:<owner>@<owner_id>/<repo>@<repo_id> — specifically so that
    renaming or transferring the repo doesn't let a *different* future
    repo with the same name inherit trust. Confirmed empirically via a
    debug workflow step that decoded a real token's claims rather than
    assumed from older docs showing the name-only format.
  EOT
  type        = string
  default     = "repo:RakeshSim@32040828/smarthelp-telco-poc@1305412004"
}

variable "manage_github_oidc" {
  description = <<-EOT
    Whether this environment's Terraform manages the GitHub Actions OIDC
    provider + roles. The OIDC provider is an account-global resource
    (one per URL, not per environment) — only one environment should
    manage it per AWS account, so this is true for dev and false for
    qa/prod to avoid a duplicate-resource error if they ever share an
    account.
  EOT
  type        = bool
  default     = false
}

# --- Optional tiers (Phase 5) ---------------------------------------------
# Kept false so `terraform apply` never provisions anything that costs money
# beyond the always-free-tier LIVE services. Flip to true deliberately and
# review the module's cost notes first.

variable "enable_tier2" {
  description = "Enable Tier 2: RDS PostgreSQL + private-subnet VPC (no NAT Gateway). Costs ~$12-15/mo for db.t4g.micro if left running."
  type        = bool
  default     = false
}

variable "enable_tier3" {
  description = "Enable Tier 3: Glue ETL job + OpenSearch. OpenSearch has an hourly cost even at the smallest instance size."
  type        = bool
  default     = false
}
