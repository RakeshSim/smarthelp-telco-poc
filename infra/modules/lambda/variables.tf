variable "function_name" {
  description = "Full Lambda function name, e.g. telco-support-dev-router."
  type        = string
}

variable "source_dir" {
  description = "Path to the directory containing the Lambda's Python source (zipped as-is)."
  type        = string
}

variable "handler" {
  description = "Lambda handler, e.g. handler.lambda_handler."
  type        = string
}

variable "runtime" {
  description = "Lambda runtime."
  type        = string
  default     = "python3.12"
}

variable "memory_size" {
  type    = number
  default = 128
}

variable "timeout" {
  type    = number
  default = 10
}

variable "layers" {
  description = "List of Lambda layer ARNs to attach."
  type        = list(string)
  default     = []
}

variable "environment_variables" {
  description = "Environment variables exposed to the function."
  type        = map(string)
  default     = {}
}

variable "additional_policy_json" {
  description = "Optional extra IAM policy document (JSON) to attach to the function's execution role, e.g. DynamoDB/SQS/SNS access needed by later phases. Leave null for a log-only role."
  type        = string
  default     = null
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "tags" {
  type    = map(string)
  default = {}
}
