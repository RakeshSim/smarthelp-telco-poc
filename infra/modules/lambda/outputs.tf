output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "arn" {
  value = aws_lambda_function.this.arn
}

output "invoke_arn" {
  value = aws_lambda_function.this.invoke_arn
}

output "role_name" {
  description = "Execution role name, so later phases can attach additional policies (DynamoDB/SQS/SNS) without changing this module."
  value       = aws_iam_role.this.name
}

output "role_arn" {
  value = aws_iam_role.this.arn
}
