data "aws_caller_identity" "current" {}

locals {
  function_name = "pfm-finops-manager-${var.environment}"

  common_tags = {
    Service     = "pfm-finops-manager"
    Environment = var.environment
    ManagedBy   = "OpenTofu"
    Project     = "pfm-platform"
  }
}

data "archive_file" "finops_manager_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../../../src/finops_manager"
  output_path = "${path.module}/finops_manager.zip"
}

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
    sid    = "ZeroCloudWatchAuditAndRetentionEnforcement"
    effect = "Allow"
    actions = [
      "logs:DescribeLogGroups",
      "logs:PutRetentionPolicy",
      "logs:DeleteLogGroup"
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/ecs/pfm*",
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/pfm*",
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/pfm*",
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/eks/pfm*"
    ]
  }

  statement {
    sid    = "EcsServicesParkUnpark"
    effect = "Allow"
    actions = [
      "ecs:ListServices",
      "ecs:DescribeServices",
      "ecs:UpdateService"
    ]
    resources = [
      "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/${var.ecs_cluster_name}",
      "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:service/${var.ecs_cluster_name}/*"
    ]
  }

  statement {
    sid    = "RdsParkUnpark"
    effect = "Allow"
    actions = [
      "rds:DescribeDBInstances",
      "rds:StartDBInstance",
      "rds:StopDBInstance"
    ]
    resources = [
      "arn:aws:rds:${var.aws_region}:${data.aws_caller_identity.current.account_id}:db:${var.rds_instance_id}",
      "arn:aws:rds:${var.aws_region}:${data.aws_caller_identity.current.account_id}:db:pfm-*"
    ]
  }

  statement {
    sid    = "ElastiCacheValkeyReadOnlyAudit"
    effect = "Allow"
    actions = [
      "elasticache:DescribeReplicationGroups",
      "elasticache:DescribeCacheClusters"
    ]
    resources = [
      "arn:aws:elasticache:${var.aws_region}:${data.aws_caller_identity.current.account_id}:replicationgroup:pfm-*",
      "arn:aws:elasticache:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster:pfm-*"
    ]
  }

  statement {
    sid    = "AiWorkerLambdaConcurrencyControl"
    effect = "Allow"
    actions = [
      "lambda:GetFunction",
      "lambda:PutFunctionConcurrency",
      "lambda:DeleteFunctionConcurrency"
    ]
    resources = [
      "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${var.ai_worker_function_name}",
      "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:pfm-ai-worker*"
    ]
  }

  statement {
    sid    = "ZeroCostGuardrailScopedToProjectTag"
    effect = "Allow"
    actions = [
      "eks:DescribeCluster",
      "ec2:DescribeNatGateways"
    ]
    resources = [
      "arn:aws:eks:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/pfm-*",
      "arn:aws:ec2:${var.aws_region}:${data.aws_caller_identity.current.account_id}:natgateway/*"
    ]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }
}

resource "aws_iam_role_policy" "finops_manager_least_privilege" {
  name   = "pfm-finops-manager-least-privilege-${var.environment}"
  role   = aws_iam_role.finops_manager_lambda.id
  policy = data.aws_iam_policy_document.finops_manager_least_privilege.json
}

resource "aws_cloudwatch_log_group" "finops_manager" {
  count             = var.enable_cloudwatch_logs ? 1 : 0
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 14
  kms_key_id        = var.kms_master_key_arn
  tags              = local.common_tags
}

# trivy:ignore:AVD-AWS-0066 X-Ray tracing omitted in FinOps MVP to avoid extra tracing fees
resource "aws_lambda_function" "finops_manager" {
  function_name    = local.function_name
  description      = "FinOps Park (20:30 BRT) & Unpark (06:00 BRT) for PFM ECS Fargate Spot Services, RDS PostgreSQL 16 and AI Worker Lambda (${var.environment})"
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
      ECS_CLUSTER_NAME        = var.ecs_cluster_name
      RDS_INSTANCE_ID         = var.rds_instance_id
      AI_WORKER_FUNCTION_NAME = var.ai_worker_function_name
      CLOUDWATCH_LOGS_ENABLED = "false"
      DD_SERVICE              = "pfm-finops-manager"
      DD_ENV                  = var.environment
      DD_VERSION              = "3.0.3"
      DD_LOGS_INJECTION       = "true"
      DD_TRACE_SAMPLE_RATE    = "0.10"
    }
  }

  tags = local.common_tags

  depends_on = [
    aws_iam_role_policy.finops_manager_least_privilege
  ]
}

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
  name   = "pfm-finops-scheduler-invoke-lambda-${var.environment}"
  role   = aws_iam_role.scheduler_invoke.id
  policy = data.aws_iam_policy_document.scheduler_invoke_lambda.json
}

resource "aws_scheduler_schedule" "park_nightly_2030" {
  name                         = "pfm-finops-park-nightly-2030-${var.environment}"
  description                  = "Park ECS Fargate Spot Services (0 tasks) and stop RDS PostgreSQL 16 daily at 20:30 America/Sao_Paulo"
  schedule_expression          = "cron(30 20 * * ? *)"
  schedule_expression_timezone = "America/Sao_Paulo"
  state                        = var.enable_nightly_schedule ? "ENABLED" : "DISABLED"

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
  name                         = "pfm-finops-unpark-morning-0600-${var.environment}"
  description                  = "Start RDS PostgreSQL 16 and restore ECS Fargate Spot services daily at 06:00 America/Sao_Paulo"
  schedule_expression          = "cron(0 6 * * ? *)"
  schedule_expression_timezone = "America/Sao_Paulo"
  state                        = var.enable_nightly_schedule ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.finops_manager.arn
    role_arn = aws_iam_role.scheduler_invoke.arn
    input    = jsonencode({ action = "start" })
  }
}
