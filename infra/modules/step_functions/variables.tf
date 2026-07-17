variable "name" {
  description = "State machine name."
  type        = string
}

variable "definition_template_path" {
  description = "Path to an Amazon States Language file (rendered via templatefile with template_vars)."
  type        = string
}

variable "template_vars" {
  description = "Variables interpolated into the ASL template (e.g. each Lambda's ARN)."
  type        = map(string)
}

variable "invokable_lambda_arns" {
  description = "ARNs of every Lambda this state machine's Task states invoke, so its IAM role can be scoped to exactly those functions."
  type        = list(string)
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "tags" {
  type    = map(string)
  default = {}
}
