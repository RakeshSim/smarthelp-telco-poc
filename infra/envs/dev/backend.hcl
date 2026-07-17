# Bucket/table created via the one-time bootstrap step in the README
# (state bucket + lock table don't exist until Terraform's backend does).
bucket         = "telco-support-poc-tfstate-705365103500"
key            = "dev/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "telco-support-poc-tf-locks"
encrypt        = true
