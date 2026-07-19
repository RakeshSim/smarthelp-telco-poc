output "api_endpoint" {
  description = "Base URL for the deployed API. Try GET {api_endpoint}/health"
  value       = module.http_api.api_endpoint
}

output "router_lambda_name" {
  value = module.router_lambda.function_name
}

output "sessions_table_name" {
  description = "DynamoDB table holding case session state — used in the demo to fetch a pending case's task token."
  value       = aws_dynamodb_table.sessions.name
}

output "state_machine_arn" {
  value = module.telco_workflow.arn
}

output "cases_queue_url" {
  value = aws_sqs_queue.cases.url
}

output "ops_approval_topic_arn" {
  value = aws_sns_topic.ops_approval.arn
}

output "customer_notifications_topic_arn" {
  value = aws_sns_topic.customer_notifications.arn
}

output "analytics_bucket_name" {
  value = aws_s3_bucket.analytics.bucket
}

output "athena_workgroup_name" {
  value = aws_athena_workgroup.analytics.name
}

output "glue_database_name" {
  value = aws_glue_catalog_database.analytics.name
}

output "dashboard_url" {
  description = "Direct link to the CloudWatch dashboard in the console."
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}

output "reaper_lambda_name" {
  value = module.reaper_lambda.function_name
}
