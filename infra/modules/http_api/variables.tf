variable "name" {
  description = "API Gateway HTTP API name."
  type        = string
}

variable "lambda_invoke_arn" {
  description = "invoke_arn of the Lambda function backing the $default route."
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the Lambda function, for the resource-based invoke permission."
  type        = string
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "throttle_burst_limit" {
  description = "Max concurrent requests. Kept low deliberately — this is a demo API, not production traffic."
  type        = number
  default     = 5
}

variable "throttle_rate_limit" {
  description = "Steady-state requests/second allowed."
  type        = number
  default     = 10
}

variable "tags" {
  type    = map(string)
  default = {}
}
