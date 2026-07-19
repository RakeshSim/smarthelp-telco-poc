data "aws_caller_identity" "current" {}

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

data "aws_iam_policy_document" "router_policy" {
  statement {
    sid       = "SendToCasesQueue"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.cases.arn]
  }
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
    CASES_QUEUE_URL         = aws_sqs_queue.cases.url
  }
  additional_policy_json = data.aws_iam_policy_document.router_policy.json
  has_additional_policy  = true

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

# ---------------------------------------------------------------------------
# Phase 2: durable state, messaging, config, and the Step Functions workflow
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "sessions" {
  name         = "${local.name_prefix}-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "case_id"

  attribute {
    name = "case_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = local.tags
}

# DLQ first so the main queue's redrive_policy can reference its ARN.
resource "aws_sqs_queue" "cases_dlq" {
  name                      = "${local.name_prefix}-cases-dlq"
  message_retention_seconds = 1209600 # 14 days (SQS max) — time to inspect/redrive failed messages
  tags                      = local.tags
}

resource "aws_sqs_queue" "cases" {
  name = "${local.name_prefix}-cases"
  # >= the starter Lambda's timeout, so a message isn't redelivered to a
  # second invocation while the first is still processing it.
  visibility_timeout_seconds = 30
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.cases_dlq.arn
    maxReceiveCount     = 3
  })
  tags = local.tags
}

resource "aws_sns_topic" "ops_approval" {
  name = "${local.name_prefix}-ops-approval"
  tags = local.tags
}

resource "aws_sns_topic" "customer_notifications" {
  name = "${local.name_prefix}-customer-notifications"
  tags = local.tags
}

resource "aws_sns_topic_subscription" "approver_email" {
  count     = var.approver_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.ops_approval.arn
  protocol  = "email"
  endpoint  = var.approver_email
}

resource "aws_sns_topic_subscription" "customer_email" {
  count     = var.customer_notification_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.customer_notifications.arn
  protocol  = "email"
  endpoint  = var.customer_notification_email
}

# Runtime config read by the starter Lambda — demonstrates a real config
# store rather than baking every knob into Terraform-managed env vars.
resource "aws_ssm_parameter" "max_diagnostic_attempts" {
  name  = "/${var.project_name}/${var.environment}/config/max_diagnostic_attempts"
  type  = "String"
  value = tostring(var.max_diagnostic_attempts)
  tags  = local.tags
}

# The one Secrets Manager secret called for in this project's spec — a
# mock API key for the (simulated) field-dispatch/ticketing system the
# `act` Lambda "calls" for DISPATCH actions. Costs ~$0.40/mo while it
# exists; see README Cost & Teardown. Everything else config-shaped uses
# free SSM SecureString instead.
resource "aws_secretsmanager_secret" "dispatch_api_key" {
  name                    = "${local.name_prefix}-dispatch-api-key"
  description             = "Mock API key for the simulated field-dispatch system."
  recovery_window_in_days = 0 # instant delete on `terraform destroy` — fine for a POC, not for prod
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "dispatch_api_key" {
  secret_id     = aws_secretsmanager_secret.dispatch_api_key.id
  secret_string = jsonencode({ api_key = "mock-dispatch-key-do-not-use-in-prod" })
}

# --- Workflow Lambdas (invoked by Step Functions Task states) --------------

module "diagnose_lambda" {
  source = "./modules/lambda"

  function_name = "${local.name_prefix}-diagnose"
  source_dir    = "${path.module}/../src/diagnose"
  handler       = "diagnose.lambda_handler"
  layers        = [module.powertools_layer.arn]

  environment_variables = {
    POWERTOOLS_SERVICE_NAME = "telco-diagnose"
    LOG_LEVEL               = "INFO"
  }

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

data "aws_iam_policy_document" "interpret_diagnostics_policy" {
  statement {
    sid       = "UpdateSessions"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.sessions.arn]
  }
}

module "interpret_diagnostics_lambda" {
  source = "./modules/lambda"

  function_name = "${local.name_prefix}-interpret-diagnostics"
  source_dir    = "${path.module}/../src/interpret_diagnostics"
  handler       = "interpret_diagnostics.lambda_handler"
  layers        = [module.powertools_layer.arn]

  environment_variables = {
    POWERTOOLS_SERVICE_NAME = "telco-interpret-diagnostics"
    LOG_LEVEL               = "INFO"
    SESSIONS_TABLE_NAME     = aws_dynamodb_table.sessions.name
  }
  additional_policy_json = data.aws_iam_policy_document.interpret_diagnostics_policy.json
  has_additional_policy  = true

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

data "aws_iam_policy_document" "request_approval_policy" {
  statement {
    sid       = "UpdateSessions"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.sessions.arn]
  }
  statement {
    sid       = "PublishApprovalRequest"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.ops_approval.arn]
  }
}

module "request_approval_lambda" {
  source = "./modules/lambda"

  function_name = "${local.name_prefix}-request-approval"
  source_dir    = "${path.module}/../src/request_approval"
  handler       = "request_approval.lambda_handler"
  layers        = [module.powertools_layer.arn]

  environment_variables = {
    POWERTOOLS_SERVICE_NAME = "telco-request-approval"
    LOG_LEVEL               = "INFO"
    SESSIONS_TABLE_NAME     = aws_dynamodb_table.sessions.name
    OPS_APPROVAL_TOPIC_ARN  = aws_sns_topic.ops_approval.arn
  }
  additional_policy_json = data.aws_iam_policy_document.request_approval_policy.json
  has_additional_policy  = true

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

data "aws_iam_policy_document" "act_policy" {
  statement {
    sid       = "ReadDispatchApiKey"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.dispatch_api_key.arn]
  }
}

module "act_lambda" {
  source = "./modules/lambda"

  function_name = "${local.name_prefix}-act"
  source_dir    = "${path.module}/../src/act"
  handler       = "act.lambda_handler"
  layers        = [module.powertools_layer.arn]

  environment_variables = {
    POWERTOOLS_SERVICE_NAME = "telco-act"
    LOG_LEVEL               = "INFO"
    DISPATCH_SECRET_ARN     = aws_secretsmanager_secret.dispatch_api_key.arn
  }
  additional_policy_json = data.aws_iam_policy_document.act_policy.json
  has_additional_policy  = true

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

module "interpret_results_lambda" {
  source = "./modules/lambda"

  function_name = "${local.name_prefix}-interpret-results"
  source_dir    = "${path.module}/../src/interpret_results"
  handler       = "interpret_results.lambda_handler"
  layers        = [module.powertools_layer.arn]

  environment_variables = {
    POWERTOOLS_SERVICE_NAME = "telco-interpret-results"
    LOG_LEVEL               = "INFO"
  }

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

# --- Analytics: S3 + Glue Catalog + Athena ----------------------------------
# The resolver Lambda drops one JSON record per resolved case here;
# Athena queries it directly against S3 via the Glue Catalog table below —
# no ETL job, no crawler (that's the optional Tier 3 Glue piece, left
# disabled). Partition projection means new dt= prefixes are queryable
# immediately, no MSCK REPAIR TABLE step needed.

resource "aws_s3_bucket" "analytics" {
  bucket = "${local.name_prefix}-analytics-${data.aws_caller_identity.current.account_id}"
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "analytics" {
  bucket                  = aws_s3_bucket.analytics.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "analytics" {
  bucket = aws_s3_bucket.analytics.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "analytics" {
  bucket = aws_s3_bucket.analytics.id
  rule {
    id     = "expire-old-records"
    status = "Enabled"
    filter {}
    expiration {
      days = var.analytics_retention_days
    }
  }
}

resource "aws_glue_catalog_database" "analytics" {
  name = replace("${local.name_prefix}_analytics", "-", "_")
}

resource "aws_glue_catalog_table" "resolutions" {
  name          = "resolutions"
  database_name = aws_glue_catalog_database.analytics.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification                = "json"
    "projection.enabled"          = "true"
    "projection.dt.type"          = "date"
    "projection.dt.range"         = "2026-01-01,NOW"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "storage.location.template"   = "s3://${aws_s3_bucket.analytics.bucket}/resolutions/dt=$${dt}/"
  }

  partition_keys {
    name = "dt"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.analytics.bucket}/resolutions/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "case_id"
      type = "string"
    }
    columns {
      name = "customer_id"
      type = "string"
    }
    columns {
      name = "issue_type"
      type = "string"
    }
    columns {
      name = "resolution_type"
      type = "string"
    }
    columns {
      name = "attempt"
      type = "int"
    }
    columns {
      name = "recommended_action"
      type = "string"
    }
    columns {
      name = "resolved_at"
      type = "bigint"
    }
  }
}

resource "aws_athena_workgroup" "analytics" {
  name = "${local.name_prefix}-analytics"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.analytics.bucket}/athena-results/"
    }
  }

  tags = local.tags
}

data "aws_iam_policy_document" "resolver_policy" {
  statement {
    sid       = "UpdateSessions"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.sessions.arn]
  }
  statement {
    sid       = "PublishCustomerNotification"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.customer_notifications.arn]
  }
  statement {
    sid       = "WriteAnalyticsRecords"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.analytics.arn}/resolutions/*"]
  }
}

module "resolver_lambda" {
  source = "./modules/lambda"

  function_name = "${local.name_prefix}-resolver"
  source_dir    = "${path.module}/../src/resolver"
  handler       = "resolver.lambda_handler"
  layers        = [module.powertools_layer.arn]

  environment_variables = {
    POWERTOOLS_SERVICE_NAME          = "telco-resolver"
    LOG_LEVEL                        = "INFO"
    SESSIONS_TABLE_NAME              = aws_dynamodb_table.sessions.name
    CUSTOMER_NOTIFICATIONS_TOPIC_ARN = aws_sns_topic.customer_notifications.arn
    ANALYTICS_BUCKET_NAME            = aws_s3_bucket.analytics.bucket
  }
  additional_policy_json = data.aws_iam_policy_document.resolver_policy.json
  has_additional_policy  = true

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

module "telco_workflow" {
  source = "./modules/step_functions"

  name                     = "${local.name_prefix}-workflow"
  definition_template_path = "${path.module}/state_machine/telco_workflow.asl.json.tftpl"
  template_vars = {
    diagnose_arn              = module.diagnose_lambda.arn
    interpret_diagnostics_arn = module.interpret_diagnostics_lambda.arn
    request_approval_arn      = module.request_approval_lambda.arn
    act_arn                   = module.act_lambda.arn
    interpret_results_arn     = module.interpret_results_lambda.arn
    resolver_arn              = module.resolver_lambda.arn
  }
  invokable_lambda_arns = [
    module.diagnose_lambda.arn,
    module.interpret_diagnostics_lambda.arn,
    module.request_approval_lambda.arn,
    module.act_lambda.arn,
    module.interpret_results_lambda.arn,
    module.resolver_lambda.arn,
  ]

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

# --- Starter Lambda: SQS -> DynamoDB session + Step Functions StartExecution

data "aws_iam_policy_document" "starter_policy" {
  statement {
    sid       = "WriteSessions"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.sessions.arn]
  }
  statement {
    sid       = "StartWorkflow"
    actions   = ["states:StartExecution"]
    resources = [module.telco_workflow.arn]
  }
  statement {
    sid       = "ReadConfig"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.max_diagnostic_attempts.arn]
  }
  statement {
    sid = "ConsumeCasesQueue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.cases.arn]
  }
}

module "starter_lambda" {
  source = "./modules/lambda"

  function_name = "${local.name_prefix}-starter"
  source_dir    = "${path.module}/../src/starter"
  handler       = "starter.lambda_handler"
  layers        = [module.powertools_layer.arn]

  environment_variables = {
    POWERTOOLS_SERVICE_NAME = "telco-starter"
    LOG_LEVEL               = "INFO"
    SESSIONS_TABLE_NAME     = aws_dynamodb_table.sessions.name
    STATE_MACHINE_ARN       = module.telco_workflow.arn
    MAX_ATTEMPTS_PARAM_NAME = aws_ssm_parameter.max_diagnostic_attempts.name
  }
  additional_policy_json = data.aws_iam_policy_document.starter_policy.json
  has_additional_policy  = true

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

resource "aws_lambda_event_source_mapping" "starter_from_cases_queue" {
  event_source_arn = aws_sqs_queue.cases.arn
  function_name    = module.starter_lambda.function_name
  batch_size       = 1
}

# --- Reaper: EventBridge-scheduled reconciliation ---------------------------

data "aws_iam_policy_document" "reaper_policy" {
  statement {
    sid       = "ScanAndUpdateSessions"
    actions   = ["dynamodb:Scan", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.sessions.arn]
  }
  statement {
    sid       = "InspectExecutions"
    actions   = ["states:DescribeExecution"]
    resources = ["${replace(module.telco_workflow.arn, ":stateMachine:", ":execution:")}:*"]
  }
  statement {
    sid       = "PublishNotifications"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.ops_approval.arn, aws_sns_topic.customer_notifications.arn]
  }
}

module "reaper_lambda" {
  source = "./modules/lambda"

  function_name = "${local.name_prefix}-reaper"
  source_dir    = "${path.module}/../src/reaper"
  handler       = "reaper.lambda_handler"
  layers        = [module.powertools_layer.arn]
  timeout       = 30 # a Scan across every stuck session can run longer than the 10s default

  environment_variables = {
    POWERTOOLS_SERVICE_NAME          = "telco-reaper"
    LOG_LEVEL                        = "INFO"
    SESSIONS_TABLE_NAME              = aws_dynamodb_table.sessions.name
    STATE_MACHINE_ARN                = module.telco_workflow.arn
    OPS_APPROVAL_TOPIC_ARN           = aws_sns_topic.ops_approval.arn
    CUSTOMER_NOTIFICATIONS_TOPIC_ARN = aws_sns_topic.customer_notifications.arn
    REAPER_STALE_AFTER_MINUTES       = tostring(var.reaper_stale_after_minutes)
  }
  additional_policy_json = data.aws_iam_policy_document.reaper_policy.json
  has_additional_policy  = true

  log_retention_days = var.log_retention_days
  tags               = local.tags
}

resource "aws_cloudwatch_event_rule" "reaper_schedule" {
  name                = "${local.name_prefix}-reaper-schedule"
  schedule_expression = var.reaper_schedule_expression
  tags                = local.tags
}

resource "aws_cloudwatch_event_target" "reaper" {
  rule = aws_cloudwatch_event_rule.reaper_schedule.name
  arn  = module.reaper_lambda.arn
}

resource "aws_lambda_permission" "reaper_from_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.reaper_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.reaper_schedule.arn
}

module "http_api" {
  source = "./modules/http_api"

  name                 = "${local.name_prefix}-api"
  lambda_invoke_arn    = module.router_lambda.invoke_arn
  lambda_function_name = module.router_lambda.function_name
  log_retention_days   = var.log_retention_days
  tags                 = local.tags
}

# --- CloudWatch Dashboard ----------------------------------------------------

locals {
  dashboard_lambda_names = [
    module.router_lambda.function_name,
    module.starter_lambda.function_name,
    module.diagnose_lambda.function_name,
    module.interpret_diagnostics_lambda.function_name,
    module.request_approval_lambda.function_name,
    module.act_lambda.function_name,
    module.interpret_results_lambda.function_name,
    module.resolver_lambda.function_name,
    module.reaper_lambda.function_name,
  ]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name_prefix}-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "API Gateway"
          region = var.aws_region
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiId", module.http_api.api_id],
            ["AWS/ApiGateway", "4xx", "ApiId", module.http_api.api_id],
            ["AWS/ApiGateway", "5xx", "ApiId", module.http_api.api_id],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Step Functions executions"
          region = var.aws_region
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/States", "ExecutionsStarted", "StateMachineArn", module.telco_workflow.arn],
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", module.telco_workflow.arn],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", module.telco_workflow.arn],
            ["AWS/States", "ExecutionsTimedOut", "StateMachineArn", module.telco_workflow.arn],
            ["AWS/States", "ExecutionsAborted", "StateMachineArn", module.telco_workflow.arn],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Cases queue"
          region = var.aws_region
          period = 60
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.cases.name, { stat = "Maximum" }],
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", aws_sqs_queue.cases.name, { stat = "Maximum" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Dead-letter queue depth (should stay at 0)"
          region = var.aws_region
          stat   = "Maximum"
          period = 60
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.cases_dlq.name],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          title   = "Lambda errors (all functions)"
          region  = var.aws_region
          stat    = "Sum"
          period  = 60
          metrics = [for name in local.dashboard_lambda_names : ["AWS/Lambda", "Errors", "FunctionName", name]]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 12
        width  = 12
        height = 6
        properties = {
          title  = "DynamoDB sessions table capacity"
          region = var.aws_region
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", aws_dynamodb_table.sessions.name],
            ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", aws_dynamodb_table.sessions.name],
          ]
        }
      },
    ]
  })
}
