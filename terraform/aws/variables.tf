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
  description = "ECS Cluster name managed by FinOps Manager"
  type        = string
  default     = "pfm-pilot-prod"
}

variable "eks_cluster_name" {
  description = "EKS Cluster name managed by FinOps Manager"
  type        = string
  default     = "pfm-eks-prod"
}

variable "eks_nodegroup_name" {
  description = "EKS Managed Node Group name managed by FinOps Manager"
  type        = string
  default     = "pfm-eks-prod-graviton-mvp"
}

variable "rds_instance_id" {
  description = "RDS PostgreSQL DB instance identifier managed by FinOps Manager"
  type        = string
  default     = "pfm-core-ledger-prod"
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
