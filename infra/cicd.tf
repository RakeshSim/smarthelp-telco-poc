# --- GitHub Actions OIDC: CI/CD without long-lived AWS access keys --------
#
# Two roles, not one, on purpose:
#   - `gha_plan`  is assumable by GitHub Actions runs on ANY ref in this
#     repo (including PRs) and only holds read-only permissions — safe to
#     let a pull request's workflow assume, since it can't change anything.
#   - `gha_apply` is assumable ONLY when the OIDC token's `sub` claim is
#     exactly `repo:<github_repo>:ref:refs/heads/main` — i.e. only a
#     workflow run triggered by a push (merge) to `main`, never a PR from
#     this repo or a fork. It holds the actual write permissions.
# A single broadly-trusted role with write access would mean any PR
# workflow could assume the write-capable role — this split is the whole
# point of having two roles instead of one.

resource "aws_iam_openid_connect_provider" "github_actions" {
  count = var.manage_github_oidc ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # AWS now validates GitHub's OIDC certificate chain automatically for
  # this well-known provider URL regardless of the value here — a
  # thumbprint is still a required argument to create the resource, so
  # this is GitHub's documented root CA thumbprint for that purpose.
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "gha_plan_trust" {
  count = var.manage_github_oidc ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions[0].arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

data "aws_iam_policy_document" "gha_apply_trust" {
  count = var.manage_github_oidc ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions[0].arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test = "StringEquals"
      # Only a push to main — never a pull_request event, from this repo
      # or a fork — can assume the role with write access.
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "gha_plan" {
  count              = var.manage_github_oidc ? 1 : 0
  name               = "${local.name_prefix}-gha-plan"
  assume_role_policy = data.aws_iam_policy_document.gha_plan_trust[0].json
  tags               = local.tags
}

resource "aws_iam_role" "gha_apply" {
  count              = var.manage_github_oidc ? 1 : 0
  name               = "${local.name_prefix}-gha-apply"
  assume_role_policy = data.aws_iam_policy_document.gha_apply_trust[0].json
  tags               = local.tags
}

# Terraform's S3 backend needs read (plan) or read/write (apply) access to
# its own state object, plus the DynamoDB lock item — for both roles, this
# is scoped to exactly this project's state key and lock table, never the
# project's actual live resources.
data "aws_iam_policy_document" "terraform_backend_access" {
  count = var.manage_github_oidc ? 1 : 0

  statement {
    sid       = "StateObject"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["arn:aws:s3:::telco-support-poc-tfstate-${data.aws_caller_identity.current.account_id}/${var.environment}/*"]
  }
  statement {
    sid       = "StateLock"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = ["arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/telco-support-poc-tf-locks"]
  }
}

resource "aws_iam_role_policy" "gha_plan_backend" {
  count  = var.manage_github_oidc ? 1 : 0
  name   = "${local.name_prefix}-gha-plan-backend"
  role   = aws_iam_role.gha_plan[0].id
  policy = data.aws_iam_policy_document.terraform_backend_access[0].json
}

resource "aws_iam_role_policy" "gha_apply_backend" {
  count  = var.manage_github_oidc ? 1 : 0
  name   = "${local.name_prefix}-gha-apply-backend"
  role   = aws_iam_role.gha_apply[0].id
  policy = data.aws_iam_policy_document.terraform_backend_access[0].json
}

# Plan only ever needs to read/diff — AWS's own ReadOnlyAccess managed
# policy is the appropriate scope for a role a pull request can assume.
resource "aws_iam_role_policy_attachment" "gha_plan_readonly" {
  count      = var.manage_github_oidc ? 1 : 0
  role       = aws_iam_role.gha_plan[0].name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# Apply needs to create/update/destroy the actual project resources.
# Resource ARNs for most of these services aren't known ahead of the
# first apply (Terraform creates them), so this is scoped by *service*
# rather than by resource — except IAM, which gets its own tightly-scoped
# statement below, since letting the apply role manage IAM entities
# outside this project's naming convention would let a merge to main
# escalate privileges anywhere in the account.
data "aws_iam_policy_document" "gha_apply_project" {
  count = var.manage_github_oidc ? 1 : 0

  statement {
    sid = "ProjectServices"
    actions = [
      "lambda:*",
      "apigateway:*",
      "dynamodb:*",
      "sqs:*",
      "sns:*",
      "ssm:*",
      "secretsmanager:*",
      "states:*",
      "s3:*",
      "glue:*",
      "athena:*",
      "events:*",
      "logs:*",
      "cloudwatch:*",
    ]
    resources = ["*"]
  }

  statement {
    sid = "ScopedIamForProjectRolesOnly"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:TagRole",
      "iam:PutRolePolicy",
      "iam:GetRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:ListRolePolicies",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:PassRole",
    ]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-*"]
  }

  statement {
    sid       = "WhoAmI"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "gha_apply_project" {
  count  = var.manage_github_oidc ? 1 : 0
  name   = "${local.name_prefix}-gha-apply-project"
  role   = aws_iam_role.gha_apply[0].id
  policy = data.aws_iam_policy_document.gha_apply_project[0].json
}
