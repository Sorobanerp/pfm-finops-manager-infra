variable "aws_region" {
  description = "Primary AWS Region (Ohio)"
  type        = string
  default     = "us-east-2"
}

variable "environment" {
  description = "Deployment environment identifier (dev or prod)"
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

variable "kms_master_key_arn" {
  description = "KMS Master Key ARN from pfm-shared-infra"
  type        = string
  default     = null
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

variable "desired_count" {
  description = "Scale-to-Zero Bootstrap desired count reference (0 during bootstrap)"
  type        = number
  default     = 0
}

variable "min_capacity" {
  description = "Scale-to-Zero Bootstrap min capacity reference (0 during bootstrap)"
  type        = number
  default     = 0
}

variable "max_capacity" {
  description = "Scale-to-Zero Bootstrap max capacity reference (0 during bootstrap)"
  type        = number
  default     = 0
}
