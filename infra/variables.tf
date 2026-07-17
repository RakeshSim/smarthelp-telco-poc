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
