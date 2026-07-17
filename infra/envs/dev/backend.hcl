# Fill in <YOUR_UNIQUE_SUFFIX> after running the one-time bootstrap
# in the README (state bucket + lock table don't exist yet — Terraform
# can't create the backend it's about to store state in).
bucket         = "telco-support-poc-tfstate-<YOUR_UNIQUE_SUFFIX>"
key            = "dev/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "telco-support-poc-tf-locks"
encrypt        = true
