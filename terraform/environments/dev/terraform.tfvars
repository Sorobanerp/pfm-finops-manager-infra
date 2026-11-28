# =============================================================================
# pfm-finops-manager-infra — Environment: dev
# ADR-009: Scale-to-Zero Bootstrap (desired=0, min=0, max=0) & Nightly Schedule Disabled
# =============================================================================
environment             = "dev"
aws_region              = "us-east-2"
ecs_cluster_name        = "pfm-ecs-pilot-dev"
rds_instance_id         = "pfm-core-ledger-dev"
ai_worker_function_name = "pfm-ai-worker-python-dev"
enable_nightly_schedule = false
enable_cloudwatch_logs  = false
desired_count           = 0 # Post-ECR rollout target: 1
min_capacity            = 0 # Post-ECR rollout target: 1
max_capacity            = 0 # Post-ECR rollout target: 1
