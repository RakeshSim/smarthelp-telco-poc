resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/states/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = var.tags
}

# Scoped to exactly the Lambdas this workflow's Task states invoke —
# not lambda:InvokeFunction on "*".
data "aws_iam_policy_document" "invoke_lambdas" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = var.invokable_lambda_arns
  }
}

resource "aws_iam_role_policy" "invoke_lambdas" {
  name   = "${var.name}-invoke-lambdas"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.invoke_lambdas.json
}

# AWS's own CloudWatch Logs integration for Step Functions requires these
# "LogDelivery" actions on resource "*" — there's no ARN to scope them to,
# since they manage the (account-level) log delivery subscription, not a
# specific log group. This is a documented exception to least-privilege,
# not an oversight: https://docs.aws.amazon.com/step-functions/latest/dg/cw-logs.html
data "aws_iam_policy_document" "logging" {
  statement {
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "logging" {
  name   = "${var.name}-logging"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.logging.json
}

resource "aws_sfn_state_machine" "this" {
  name     = var.name
  role_arn = aws_iam_role.this.arn
  type     = "STANDARD"

  definition = templatefile(var.definition_template_path, var.template_vars)

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.this.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tags = var.tags

  depends_on = [
    aws_iam_role_policy.invoke_lambdas,
    aws_iam_role_policy.logging,
  ]
}
