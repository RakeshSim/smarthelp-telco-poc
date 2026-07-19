environment  = "dev"
aws_region   = "us-east-1"
project_name = "telco-support"

enable_tier2 = false
enable_tier3 = false

# dev is the one environment actually deployed, so it owns the
# account-global GitHub Actions OIDC provider (see variables.tf).
manage_github_oidc = true
