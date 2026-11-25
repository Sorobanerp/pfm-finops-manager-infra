variable "aws_region" {
  description = "Primary AWS Region (Ohio)"
  type        = string
  default     = "us-east-2"
}

variable "environment" {
  description = "Deployment environment identifier"
  type        = string
  default     = "prod"
}

variable "ecs_cluster_name" {
  description = "ECS Fargate Spot Cluster name managed by FinOps Manager"
  type        = string
  default     = "pfm-ecs-pilot"
}

variable "rds_instance_id" {
  description = "RDS PostgreSQL 16 DB instance identifier managed by FinOps Manager"
  type        = string
  default     = "pfm-core-ledger-prod"
}

variable "ai_worker_function_name" {
  description = "AI Worker AWS Lambda function name managed by FinOps Manager"
  type        = string
  default     = "pfm-ai-worker-python-prod"
}

variable "shared_state_bucket" {
  description = "S3 bucket storing pfm-shared-infra remote state"
  type        = string
  default     = "sorobanerp-pfm-tfstate-us-east-2-366476833548"
}

variable "enable_nightly_schedule" {
  description = "Whether to enable nightly park/unpark EventBridge schedules (default: false for controlled manual review)"
  type        = bool
  default     = false
}

variable "enable_cloudwatch_logs" {
  description = "Disable AWS CloudWatch Logs by default (FinOps ADR-010: use Datadog JSON stdout instead of CloudWatch)"
  type        = bool
  default     = false
}
