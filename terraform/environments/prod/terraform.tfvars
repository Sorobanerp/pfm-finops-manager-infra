# =============================================================================
# pfm-finops-manager-infra — Environment: prod
# ADR-009: Scale-to-Zero Bootstrap (desired=0, min=0, max=0) & Nightly Schedule Disabled
# =============================================================================
environment             = "prod"
aws_region              = "us-east-2"
ecs_cluster_name        = "pfm-ecs-pilot-prod"
rds_instance_id         = "pfm-core-ledger-prod"
ai_worker_function_name = "pfm-ai-worker-python-prod"
enable_nightly_schedule = false
enable_cloudwatch_logs  = false
desired_count           = 0 # Post-ECR rollout target: 1
min_capacity            = 0 # Post-ECR rollout target: 1
max_capacity            = 0 # Post-ECR rollout target: 3
