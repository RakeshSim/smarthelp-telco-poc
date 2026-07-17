locals {
  name_prefix = "${var.project_name}-${var.environment}"
  tags = {
    Project     = "telco-support-poc"
    Environment = var.environment
  }
}

module "powertools_layer" {
  source = "./modules/lambda_layer"

  name              = "${local.name_prefix}-powertools"
  requirements_path = "${path.module}/../src/layers/powertools/requirements.txt"
}

module "router_lambda" {
  source = "./modules/lambda"

  function_name = "${local.name_prefix}-router"
  source_dir    = "${path.module}/../src/router"
  handler       = "handler.lambda_handler"
  layers        = [module.powertools_layer.arn]

  environment_variables = {
    POWERTOOLS_SERVICE_NAME = "telco-router"
    LOG_LEVEL               = "INFO"
    ENVIRONMENT             = var.environment
  }

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

module "http_api" {
  source = "./modules/http_api"

  name                 = "${local.name_prefix}-api"
  lambda_invoke_arn    = module.router_lambda.invoke_arn
  lambda_function_name = module.router_lambda.function_name
  log_retention_days   = var.log_retention_days
  tags                 = local.tags
}
