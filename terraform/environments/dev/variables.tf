variable "aws_region" {
  description = "Primary AWS Region (Ohio)"
  type        = string
  default     = "us-east-2"
}

variable "environment" {
  description = "Deployment environment identifier (dev or prod)"
  type        = string
}

variable "ecs_cluster_name" {
  description = "ECS Fargate Spot Cluster name managed by FinOps Manager"
  type        = string
}

variable "rds_instance_id" {
  description = "RDS PostgreSQL 16 DB instance identifier managed by FinOps Manager"
  type        = string
}

variable "ai_worker_function_name" {
  description = "AI Worker AWS Lambda function name managed by FinOps Manager"
  type        = string
}

variable "shared_state_bucket" {
  description = "S3 bucket storing pfm-shared-infra remote state"
  type        = string
  default     = "sorobanerp-pfm-tfstate-us-east-2-366476833548"
}

variable "enable_nightly_schedule" {
  description = "Whether to enable nightly park/unpark EventBridge schedules (default: false)"
  type        = bool
  default     = false
}

variable "enable_cloudwatch_logs" {
  description = "Disable AWS CloudWatch Logs by default (FinOps ADR-010)"
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
