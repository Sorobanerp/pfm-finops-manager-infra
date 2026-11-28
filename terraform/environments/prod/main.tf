provider "aws" {
  region = var.aws_region
}

data "terraform_remote_state" "shared" {
  backend = "s3"
  config = {
    bucket = var.shared_state_bucket
    key    = "pfm-shared/${var.environment}/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  ecs_cluster_name   = try(data.terraform_remote_state.shared.outputs.ecs_cluster_name, var.ecs_cluster_name)
  kms_master_key_arn = try(data.terraform_remote_state.shared.outputs.kms_master_key_arn, null)
}

module "finops_manager" {
  source                  = "../../modules/finops-manager"
  aws_region              = var.aws_region
  environment             = var.environment
  ecs_cluster_name        = local.ecs_cluster_name
  rds_instance_id         = var.rds_instance_id
  ai_worker_function_name = var.ai_worker_function_name
  kms_master_key_arn      = local.kms_master_key_arn
  enable_nightly_schedule = var.enable_nightly_schedule
  enable_cloudwatch_logs  = var.enable_cloudwatch_logs
  desired_count           = var.desired_count
  min_capacity            = var.min_capacity
  max_capacity            = var.max_capacity
}
