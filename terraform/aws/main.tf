terraform {
  required_version = ">= 1.8.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

data "terraform_remote_state" "shared" {
  backend = "s3"
  config = {
    bucket = var.shared_state_bucket
    key    = "pfm-shared-infra/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  eks_cluster_name   = try(data.terraform_remote_state.shared.outputs.eks_cluster_name, var.eks_cluster_name)
  kms_master_key_arn = try(data.terraform_remote_state.shared.outputs.kms_master_key_arn, null)

  common_tags = {
    Service     = "pfm-finops-manager"
    Environment = var.environment
    ManagedBy   = "OpenTofu"
    Project     = "pfm-platform"
  }
}

# =============================================================================
# 1. Package Lambda Source Code (Arm64 Python 3.12)
# =============================================================================

data "archive_file" "finops_manager_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../../src/finops_manager"
  output_path = "${path.module}/finops_manager.zip"
}

# =============================================================================
# 2. Least-Privilege IAM Role for FinOps Manager Lambda
# =============================================================================

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "finops_manager_lambda" {
  name               = "pfm-finops-manager-lambda-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "finops_manager_least_privilege" {
  statement {
    sid    = "CloudWatchLogsWrite"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/pfm-finops-manager:*"
    ]
  }

  statement {
    sid    = "EksNodeGroupParkUnpark"
    effect = "Allow"
    actions = [
      "eks:DescribeNodegroup",
      "eks:UpdateNodegroupConfig"
    ]
    resources = [
      "arn:aws:eks:${var.aws_region}:${data.aws_caller_identity.current.account_id}:nodegroup/${local.eks_cluster_name}/${var.eks_nodegroup_name}/*"
    ]
  }

  statement {
    sid    = "RdsParkUnpark"
    effect = "Allow"
    actions = [
      "rds:DescribeDBInstances",
      "rds:StopDBInstance",
      "rds:StartDBInstance"
    ]
    resources = [
      "arn:aws:rds:${var.aws_region}:${data.aws_caller_identity.current.account_id}:db:${var.rds_instance_id}"
    ]
  }
}

resource "aws_iam_role_policy" "finops_manager_least_privilege" {
  name   = "pfm-finops-manager-least-privilege"
  role   = aws_iam_role.finops_manager_lambda.id
  policy = data.aws_iam_policy_document.finops_manager_least_privilege.json
}

resource "aws_cloudwatch_log_group" "finops_manager" {
  name              = "/aws/lambda/pfm-finops-manager"
  retention_in_days = 14
  kms_key_id        = local.kms_master_key_arn
  tags              = local.common_tags
}

# =============================================================================
# 3. Lambda Function (Python 3.12 Arm64, 128MB, 60s timeout)
# =============================================================================

# trivy:ignore:AVD-AWS-0066 X-Ray tracing omitted in FinOps MVP to avoid extra tracing fees
resource "aws_lambda_function" "finops_manager" {
  function_name    = "pfm-finops-manager"
  description      = "FinOps Park (20:30 BRT) & Unpark (06:00 BRT) for PFM EKS NodeGroup and RDS"
  role             = aws_iam_role.finops_manager_lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  memory_size      = 128
  timeout          = 60
  filename         = data.archive_file.finops_manager_zip.output_path
  source_code_hash = data.archive_file.finops_manager_zip.output_base64sha256

  environment {
    variables = {
      EKS_CLUSTER_NAME   = local.eks_cluster_name
      EKS_NODEGROUP_NAME = var.eks_nodegroup_name
      RDS_INSTANCE_ID    = var.rds_instance_id
    }
  }

  tags = local.common_tags

  depends_on = [
    aws_cloudwatch_log_group.finops_manager,
    aws_iam_role_policy.finops_manager_least_privilege
  ]
}

# =============================================================================
# 4. EventBridge Scheduler (Park 20:30 BRT & Unpark 06:00 BRT)
# =============================================================================

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler_invoke" {
  name               = "pfm-finops-scheduler-invoke-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "scheduler_invoke_lambda" {
  statement {
    sid       = "InvokeFinOpsManagerLambda"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.finops_manager.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  name   = "pfm-finops-scheduler-invoke-lambda"
  role   = aws_iam_role.scheduler_invoke.id
  policy = data.aws_iam_policy_document.scheduler_invoke_lambda.json
}

resource "aws_scheduler_schedule" "park_nightly_2030" {
  name                         = "pfm-finops-park-nightly-2030"
  description                  = "Park EKS NodeGroup (0 nodes) and stop RDS daily at 20:30 America/Sao_Paulo"
  schedule_expression          = "cron(30 20 * * ? *)"
  schedule_expression_timezone = "America/Sao_Paulo"
  state                        = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.finops_manager.arn
    role_arn = aws_iam_role.scheduler_invoke.arn
    input    = jsonencode({ action = "stop" })
  }
}

resource "aws_scheduler_schedule" "unpark_morning_0600" {
  name                         = "pfm-finops-unpark-morning-0600"
  description                  = "Start RDS and restore EKS NodeGroup (1..2 nodes) daily at 06:00 America/Sao_Paulo"
  schedule_expression          = "cron(0 6 * * ? *)"
  schedule_expression_timezone = "America/Sao_Paulo"
  state                        = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.finops_manager.arn
    role_arn = aws_iam_role.scheduler_invoke.arn
    input    = jsonencode({ action = "start" })
  }
}
