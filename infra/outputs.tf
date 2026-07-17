output "api_endpoint" {
  description = "Base URL for the deployed API. Try GET {api_endpoint}/health"
  value       = module.http_api.api_endpoint
}

output "router_lambda_name" {
  value = module.router_lambda.function_name
}
