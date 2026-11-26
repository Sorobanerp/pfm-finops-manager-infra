"""PFM FinOps Manager AWS Lambda handler.

Manages ECS Fargate Spot services (pfm-ecs-pilot), RDS PostgreSQL 16
(pfm-core-ledger-prod), and AI Worker Lambda (pfm-ai-worker-python-prod) for
nightly park (20:30 BRT) and morning unpark (06:00 BRT), and provides
real-time FinOps audit reports with zero-EKS / zero-NAT-Gateway guardrails.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


EXPECTED_ECS_SERVICES: tuple[str, ...] = (
    "pfm-core-ledger-java",
    "pfm-forecast-engine-go",
    "pfm-ingestion-bff-go",
    "pfm-web-nextjs",
)
ELASTICACHE_REPLICATION_GROUP_ID = "pfm-forecast-valkey-prod"
ZERO_CLOUDWATCH_LOG_PREFIXES: tuple[str, ...] = (
    "/ecs/pfm",
    "/aws/lambda/pfm",
    "/aws/pfm",
    "/aws/eks/pfm",
)


def _get_config() -> tuple[str, str, str, str]:
    region = os.environ.get("AWS_REGION", "us-east-2")
    ecs_cluster = os.environ.get("ECS_CLUSTER_NAME", "pfm-ecs-pilot")
    rds_identifier = os.environ.get("RDS_INSTANCE_ID", "pfm-core-ledger-prod")
    ai_worker_lambda = os.environ.get("AI_WORKER_FUNCTION_NAME", "pfm-ai-worker-python-prod")
    return region, ecs_cluster, rds_identifier, ai_worker_lambda


def _get_clients(
    region: str,
    ecs_client: Any = None,
    rds_client: Any = None,
    lambda_client: Any = None,
    ec2_client: Any = None,
    eks_client: Any = None,
    logs_client: Any = None,
) -> tuple[Any, Any, Any, Any, Any, Any]:
    if (
        ecs_client is not None
        and rds_client is not None
        and lambda_client is not None
        and ec2_client is not None
        and eks_client is not None
    ):
        return ecs_client, rds_client, lambda_client, ec2_client, eks_client, logs_client

    import boto3

    ecs = ecs_client or boto3.client("ecs", region_name=region)
    rds = rds_client or boto3.client("rds", region_name=region)
    lmb = lambda_client or boto3.client("lambda", region_name=region)
    ec2 = ec2_client or boto3.client("ec2", region_name=region)
    eks = eks_client or getattr(boto3, "client")("eks", region_name=region)
    logs = logs_client or getattr(boto3, "client")("logs", region_name=region)
    return ecs, rds, lmb, ec2, eks, logs


def _describe_ecs_services(ecs: Any, ecs_cluster: str) -> list[dict[str, Any]]:
    try:
        service_arns = ecs.list_services(cluster=ecs_cluster).get("serviceArns", [])
        if not service_arns:
            return []
        services = ecs.describe_services(cluster=ecs_cluster, services=service_arns).get("services", [])
        return [
            {
                "service_name": svc.get("serviceName"),
                "status": svc.get("status"),
                "desired_count": svc.get("desiredCount", 0),
                "running_count": svc.get("runningCount", 0),
                "desiredCount": svc.get("desiredCount", 0),
                "runningCount": svc.get("runningCount", 0),
            }
            for svc in services
        ]
    except Exception as exc:  # pylint: disable=broad-except
        return [{"error": str(exc), "cluster": ecs_cluster}]


def _describe_ai_worker_lambda(lmb: Any, function_name: str) -> dict[str, Any]:
    try:
        resp = lmb.get_function(FunctionName=function_name)
        cfg = resp.get("Configuration", {})
        concurrency = resp.get("Concurrency", {})
        return {
            "function_name": cfg.get("FunctionName", function_name),
            "function_arn": cfg.get("FunctionArn", ""),
            "state": cfg.get("State", "Active"),
            "runtime": cfg.get("Runtime", "python3.12"),
            "reserved_concurrent_executions": concurrency.get("ReservedConcurrentExecutions"),
        }
    except Exception as exc:  # pylint: disable=broad-except
        return {
            "function_name": function_name,
            "state": "NOT_FOUND_OR_ERROR",
            "error": str(exc),
        }


def _check_cost_guardrails(ec2: Any, eks: Any, logs: Any = None) -> dict[str, Any]:
    alerts: list[str] = []
    eks_clusters: list[str] = []
    active_nat_gateways: list[str] = []
    residual_log_groups: list[str] = []

    if eks is not None:
        try:
            eks_clusters = eks.list_clusters().get("clusters", [])
            if eks_clusters:
                alerts.append(f"CRITICAL_COST_ALERT: Active EKS clusters detected: {eks_clusters}")
        except Exception:  # pylint: disable=broad-except
            eks_clusters = []

    if ec2 is not None:
        try:
            nat_resp = ec2.describe_nat_gateways(
                Filters=[{"Name": "state", "Values": ["available", "pending"]}]
            )
            active_nat_gateways = [
                ng.get("NatGatewayId", "unknown") for ng in nat_resp.get("NatGateways", [])
            ]
            if active_nat_gateways:
                alerts.append(
                    f"CRITICAL_COST_ALERT: Active NAT Gateways detected: {active_nat_gateways}"
                )
        except Exception:  # pylint: disable=broad-except
            active_nat_gateways = []

    if logs is not None:
        for prefix in ZERO_CLOUDWATCH_LOG_PREFIXES:
            try:
                lg_resp = logs.describe_log_groups(logGroupNamePrefix=prefix)
                for lg in lg_resp.get("logGroups", []):
                    lg_name = lg.get("logGroupName", "")
                    if lg_name and lg_name not in residual_log_groups:
                        residual_log_groups.append(lg_name)
                        try:
                            logs.put_retention_policy(logGroupName=lg_name, retentionInDays=1)
                        except Exception:  # pylint: disable=broad-except
                            pass
            except Exception:  # pylint: disable=broad-except
                pass
        if residual_log_groups:
            alerts.append(
                f"ZERO_CLOUDWATCH_ALERT: Residual CloudWatch Log Groups detected (enforced 1-day min retention; forward to Datadog): {residual_log_groups}"
            )

    return {
        "eks_clusters_detected": eks_clusters,
        "active_nat_gateways_detected": active_nat_gateways,
        "residual_cloudwatch_log_groups": residual_log_groups,
        "zero_cloudwatch_policy": os.environ.get("CLOUDWATCH_LOGS_ENABLED", "false").lower() == "false",
        "datadog_service": os.environ.get("DD_SERVICE", "pfm-finops-manager"),
        "alerts": alerts,
    }


def _describe_state(
    ecs: Any,
    rds: Any,
    lmb: Any,
    ec2: Any,
    eks: Any,
    ecs_cluster: str,
    rds_id: str,
    ai_worker_lambda: str,
    logs: Any = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ecs": {
            "cluster_name": ecs_cluster,
            "expected_services": list(EXPECTED_ECS_SERVICES),
            "services": _describe_ecs_services(ecs, ecs_cluster),
        },
        "elasticache": {
            "replication_group_id": ELASTICACHE_REPLICATION_GROUP_ID,
            "engine": "valkey",
        },
    }

    try:
        rds_resp = rds.describe_db_instances(DBInstanceIdentifier=rds_id)["DBInstances"][0]
        rds_status = rds_resp.get("DBInstanceStatus")
        state["rds"] = {
            "db_instance_identifier": rds_id,
            "status": rds_status,
            "DBInstanceStatus": rds_status,
            "instance_class": rds_resp.get("DBInstanceClass"),
        }
    except Exception as exc:  # pylint: disable=broad-except
        state["rds"] = {
            "db_instance_identifier": rds_id,
            "status": "NOT_FOUND_OR_ERROR",
            "DBInstanceStatus": "NOT_FOUND_OR_ERROR",
            "error": str(exc),
        }

    state["ai_worker_lambda"] = _describe_ai_worker_lambda(lmb, ai_worker_lambda)
    state["cost_guardrails"] = _check_cost_guardrails(ec2, eks, logs=logs)
    return state


def _audit_resources(state: dict[str, Any]) -> dict[str, Any]:
    active: list[str] = []
    stopped: list[str] = []

    # 1. ECS Services
    for svc in state.get("ecs", {}).get("services", []):
        name = svc.get("service_name", "unknown")
        if svc.get("running_count", 0) > 0 or svc.get("desired_count", 0) > 0:
            active.append(f"ecs:{name}(desired={svc.get('desired_count')},running={svc.get('running_count')})")
        else:
            stopped.append(f"ecs:{name}(desired=0,running=0)")

    # 2. RDS Instance
    rds_data = state.get("rds", {})
    rds_status = rds_data.get("status")
    if rds_status == "available":
        active.append(f"rds:{rds_data.get('db_instance_identifier')}(available)")
    elif rds_status in {"stopped", "stopping"}:
        stopped.append(f"rds:{rds_data.get('db_instance_identifier')}({rds_status})")

    # 3. AI Worker Lambda
    lmb_data = state.get("ai_worker_lambda", {})
    lmb_name = lmb_data.get("function_name", "pfm-ai-worker-python-prod")
    reserved = lmb_data.get("reserved_concurrent_executions")
    if reserved == 0:
        stopped.append(f"lambda:{lmb_name}(frozen_concurrency=0)")
    elif lmb_data.get("state") == "Active":
        active.append(f"lambda:{lmb_name}(Active,serverless_idle_cost=$0)")

    # Estimated monthly run rate:
    # ECS Fargate Spot Arm64: ~$5.40/mo per active service task (24x7)
    # RDS db.t4g.micro: ~$12.00/mo (when running 24x7)
    # Lambda: $0.00 when idle (covered by AWS Free Tier)
    active_ecs_count = sum(1 for item in active if item.startswith("ecs:"))
    rds_running = any(item.startswith("rds:") and "available" in item for item in active)
    monthly_estimate = (active_ecs_count * 5.40) + (12.00 if rds_running else 0.0)

    guardrails = state.get("cost_guardrails", {})
    return {
        "action": "audit",
        "timestamp": state["timestamp"],
        "active_resources_count": len(active),
        "stopped_resources_count": len(stopped),
        "active_resources": active,
        "stopped_resources": stopped,
        "monthly_run_rate_estimate_usd": round(monthly_estimate, 2),
        "alerts": guardrails.get("alerts", []),
        "cost_guardrails": guardrails,
        "detailed_state": state,
    }


def _park_resources(
    ecs: Any,
    rds: Any,
    lmb: Any,
    ec2: Any,
    eks: Any,
    ecs_cluster: str,
    rds_id: str,
    ai_worker_lambda: str,
    freeze_lambda: bool = False,
) -> dict[str, Any]:
    state = _describe_state(ecs, rds, lmb, ec2, eks, ecs_cluster, rds_id, ai_worker_lambda)
    results: dict[str, Any] = {
        "action": "stop",
        "ecs_results": {},
        "rds_result": "noop",
        "lambda_result": "idle_zero_cost_no_freeze",
    }

    # 1. Scale all ECS Fargate Spot services in pfm-ecs-pilot to desiredCount=0
    for svc in state.get("ecs", {}).get("services", []):
        s_name = svc.get("service_name")
        if not s_name:
            continue
        if svc.get("desired_count", 0) == 0:
            results["ecs_results"][s_name] = "already_zero"
        else:
            try:
                ecs.update_service(cluster=ecs_cluster, service=s_name, desiredCount=0)
                results["ecs_results"][s_name] = "scaled_to_zero"
            except Exception as exc:  # pylint: disable=broad-except
                results["ecs_results"][s_name] = f"error: {exc}"

    # 2. Stop RDS PostgreSQL 16 if available
    rds_status = state.get("rds", {}).get("status")
    if rds_status == "available":
        try:
            rds.stop_db_instance(DBInstanceIdentifier=rds_id)
            results["rds_result"] = "stopping"
        except Exception as exc:  # pylint: disable=broad-except
            results["rds_result"] = f"error: {exc}"
    elif rds_status in {"stopped", "stopping"}:
        results["rds_result"] = f"already_{rds_status}"
    else:
        results["rds_result"] = f"skipped_status_{rds_status}"

    # 3. Optionally freeze AI Worker Lambda concurrency to 0
    if freeze_lambda:
        try:
            lmb.put_function_concurrency(
                FunctionName=ai_worker_lambda,
                ReservedConcurrentExecutions=0,
            )
            results["lambda_result"] = "frozen_concurrency_0"
        except Exception as exc:  # pylint: disable=broad-except
            results["lambda_result"] = f"error: {exc}"

    results["state_before"] = state
    return results


def _unpark_resources(
    ecs: Any,
    rds: Any,
    lmb: Any,
    ec2: Any,
    eks: Any,
    ecs_cluster: str,
    rds_id: str,
    ai_worker_lambda: str,
) -> dict[str, Any]:
    state = _describe_state(ecs, rds, lmb, ec2, eks, ecs_cluster, rds_id, ai_worker_lambda)
    results: dict[str, Any] = {
        "action": "start",
        "rds_result": "noop",
        "ecs_results": {},
        "lambda_result": "noop",
    }

    # 1. Start RDS PostgreSQL 16 if stopped
    rds_status = state.get("rds", {}).get("status")
    if rds_status == "stopped":
        try:
            rds.start_db_instance(DBInstanceIdentifier=rds_id)
            results["rds_result"] = "starting"
        except Exception as exc:  # pylint: disable=broad-except
            results["rds_result"] = f"error: {exc}"
    elif rds_status in {"available", "starting"}:
        results["rds_result"] = f"already_{rds_status}"
    else:
        results["rds_result"] = f"skipped_status_{rds_status}"

    # 2. Scale all ECS Fargate Spot services in pfm-ecs-pilot to desiredCount=1
    for svc in state.get("ecs", {}).get("services", []):
        s_name = svc.get("service_name")
        if not s_name:
            continue
        if svc.get("desired_count", 0) == 1:
            results["ecs_results"][s_name] = "already_at_1"
        else:
            try:
                ecs.update_service(cluster=ecs_cluster, service=s_name, desiredCount=1)
                results["ecs_results"][s_name] = "restored_to_1"
            except Exception as exc:  # pylint: disable=broad-except
                results["ecs_results"][s_name] = f"error: {exc}"

    # 3. Remove any concurrency freeze from AI Worker Lambda
    try:
        lmb.delete_function_concurrency(FunctionName=ai_worker_lambda)
        results["lambda_result"] = "concurrency_unfrozen"
    except Exception as exc:  # pylint: disable=broad-except
        results["lambda_result"] = f"error: {exc}"

    results["state_before"] = state
    return results


def lambda_handler(
    event: dict[str, Any] | None,
    context: Any = None,  # pylint: disable=unused-argument
    *,
    ecs_client: Any = None,
    rds_client: Any = None,
    lambda_client: Any = None,
    ec2_client: Any = None,
    eks_client: Any = None,
    logs_client: Any = None,
) -> dict[str, Any]:
    """Entry point for FinOps Manager Lambda supporting stop, start, status, and audit actions."""
    payload = event or {}
    if isinstance(payload.get("body"), str):
        payload = json.loads(payload["body"])

    action = str(payload.get("action", "status")).strip().lower()
    freeze_lambda = bool(payload.get("freeze_lambda", False))

    region, ecs_cluster, rds_id, ai_worker_lambda = _get_config()
    ecs, rds, lmb, ec2, eks, logs = _get_clients(
        region,
        ecs_client=ecs_client,
        rds_client=rds_client,
        lambda_client=lambda_client,
        ec2_client=ec2_client,
        eks_client=eks_client,
        logs_client=logs_client,
    )

    if action == "status":
        body: dict[str, Any] = {
            "action": "status",
            **_describe_state(
                ecs, rds, lmb, ec2, eks, ecs_cluster, rds_id, ai_worker_lambda, logs=logs
            ),
        }
    elif action == "audit":
        state = _describe_state(
            ecs, rds, lmb, ec2, eks, ecs_cluster, rds_id, ai_worker_lambda, logs=logs
        )
        body = _audit_resources(state)
    elif action == "stop":
        body = _park_resources(
            ecs,
            rds,
            lmb,
            ec2,
            eks,
            ecs_cluster,
            rds_id,
            ai_worker_lambda,
            freeze_lambda=freeze_lambda,
        )
    elif action == "start":
        body = _unpark_resources(ecs, rds, lmb, ec2, eks, ecs_cluster, rds_id, ai_worker_lambda)
    else:
        return {
            "statusCode": 400,
            "body": json.dumps(
                {"error": f"Unsupported action '{action}'. Expected stop, start, status, or audit."}
            ),
        }

    print(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "INFO",
                "service": os.environ.get("DD_SERVICE", "pfm-finops-manager"),
                "env": os.environ.get("DD_ENV", "prod"),
                "version": os.environ.get("DD_VERSION", "3.0.3"),
                "cloudwatch_logs_enabled": False,
                "finops.action": action,
            }
        )
    )
    return {"statusCode": 200, "body": json.dumps(body)}
