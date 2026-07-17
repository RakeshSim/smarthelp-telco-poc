provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "telco-support-poc"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
