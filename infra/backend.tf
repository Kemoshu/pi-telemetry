# Remote state: S3 for the state file, DynamoDB for the lock.
# The bucket and lock table are created once, outside this stack (see README).
# Values live in backend.hcl (gitignored), initialize with:
#   terraform init -backend-config=backend.hcl
terraform {
  backend "s3" {}
}
