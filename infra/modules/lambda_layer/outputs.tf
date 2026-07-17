output "arn" {
  description = "ARN of the published layer version."
  value       = aws_lambda_layer_version.this.arn
}
