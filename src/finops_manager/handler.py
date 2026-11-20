"""PFM FinOps Manager AWS Lambda handler.

Manages ECS Fargate Spot services, RDS PostgreSQL, and EKS Node Groups for
nightly park (20:30 BRT) and morning unpark (06:00 BRT), and provides
consolidated FinOps audit reports.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


def _get_config() -> tuple[str, str, str, str, str]:
    region = os.environ.get("AWS_REGION", "us-east-2")
    ecs_cluster = os.environ.get("ECS_CLUSTER_NAME", "pfm-pilot-prod")
    cluster_name = os.environ.get("EKS_CLUSTER_NAME", "pfm-eks-prod")
    nodegroup_name = os.environ.get("EKS_NODEGROUP_NAME", "pfm-eks-prod-graviton-mvp")
    rds_identifier = os.environ.get("RDS_INSTANCE_ID", "pfm-core-ledger-prod")
    return region, ecs_cluster, cluster_name, nodegroup_name, rds_identifier


def _get_clients(
    region: str,
    eks_client: Any = None,
    rds_client: Any = None,
    ecs_client: Any = None,
) -> tuple[Any, Any, Any]:
    if eks_client is not None and rds_client is not None and ecs_client is not None:
        return eks_client, rds_client, ecs_client
    import boto3

    eks = eks_client or boto3.client("eks", region_name=region)
    rds = rds_client or boto3.client("rds", region_name=region)
    ecs = ecs_client or boto3.client("ecs", region_name=region)
    return eks, rds, ecs


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
            }
            for svc in services
        ]
    except Exception as exc:  # pylint: disable=broad-except
        return [{"error": str(exc), "cluster": ecs_cluster}]


def _describe_state(
    eks: Any, rds: Any, ecs: Any, ecs_cluster: str, cluster_name: str, nodegroup_name: str, rds_id: str
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ecs": {
            "cluster_name": ecs_cluster,
            "services": _describe_ecs_services(ecs, ecs_cluster),
        },
    }

    try:
        ng_resp = eks.describe_nodegroup(clusterName=cluster_name, nodegroupName=nodegroup_name)["nodegroup"]
        state["eks"] = {
            "cluster_name": cluster_name,
            "nodegroup_name": nodegroup_name,
            "status": ng_resp.get("status"),
            "scaling_config": ng_resp.get("scalingConfig", {}),
        }
    except Exception as exc:  # pylint: disable=broad-except
        state["eks"] = {"cluster_name": cluster_name, "status": "NOT_FOUND_OR_ERROR", "error": str(exc)}

    try:
        rds_resp = rds.describe_db_instances(DBInstanceIdentifier=rds_id)["DBInstances"][0]
        state["rds"] = {
            "db_instance_identifier": rds_id,
            "status": rds_resp.get("DBInstanceStatus"),
            "instance_class": rds_resp.get("DBInstanceClass"),
        }
    except Exception as exc:  # pylint: disable=broad-except
        state["rds"] = {"db_instance_identifier": rds_id, "status": "NOT_FOUND_OR_ERROR", "error": str(exc)}

    return state


def _audit_resources(state: dict[str, Any]) -> dict[str, Any]:
    active: list[str] = []
    stopped: list[str] = []

    # ECS Services
    for svc in state.get("ecs", {}).get("services", []):
        name = svc.get("service_name", "unknown")
        if svc.get("running_count", 0) > 0 or svc.get("desired_count", 0) > 0:
            active.append(f"ecs:{name}(desired={svc.get('desired_count')})")
        else:
            stopped.append(f"ecs:{name}(desired=0)")

    # EKS Node Group
    eks_data = state.get("eks", {})
    if eks_data.get("status") == "ACTIVE":
        desired = eks_data.get("scaling_config", {}).get("desiredSize", 0)
        if desired > 0:
            active.append(f"eks-nodegroup:{eks_data.get('nodegroup_name')}(desired={desired})")
        else:
            stopped.append(f"eks-nodegroup:{eks_data.get('nodegroup_name')}(desired=0)")

    # RDS Instance
    rds_data = state.get("rds", {})
    rds_status = rds_data.get("status")
    if rds_status == "available":
        active.append(f"rds:{rds_data.get('db_instance_identifier')}(available)")
    elif rds_status in {"stopped", "stopping"}:
        stopped.append(f"rds:{rds_data.get('db_instance_identifier')}({rds_status})")

    # Estimated monthly run rate
    # ECS Fargate Spot: ~$0.0075/hr per 256/512 = ~$5.40/mo per active task
    # RDS db.t4g.micro: ~$12.00/mo (when running 24x7)
    active_ecs_count = sum(1 for item in active if item.startswith("ecs:"))
    rds_running = any(item.startswith("rds:") and "available" in item for item in active)
    monthly_estimate = (active_ecs_count * 5.40) + (12.00 if rds_running else 0.0)

    return {
        "action": "audit",
        "timestamp": state["timestamp"],
        "active_resources_count": len(active),
        "stopped_resources_count": len(stopped),
        "active_resources": active,
        "stopped_resources": stopped,
        "monthly_run_rate_estimate_usd": round(monthly_estimate, 2),
        "detailed_state": state,
    }


def _park_resources(
    eks: Any, rds: Any, ecs: Any, ecs_cluster: str, cluster_name: str, nodegroup_name: str, rds_id: str
) -> dict[str, Any]:
    state = _describe_state(eks, rds, ecs, ecs_cluster, cluster_name, nodegroup_name, rds_id)
    results: dict[str, Any] = {
        "action": "stop",
        "ecs_results": {},
        "eks_result": "noop",
        "rds_result": "noop",
    }

    # 1. Park ECS Fargate Spot services (scale desiredCount to 0)
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

    # 2. Park EKS Node Group (if present)
    eks_scaling = state.get("eks", {}).get("scaling_config", {})
    if eks_scaling:
        max_size = max(int(eks_scaling.get("maxSize", 2)), 1)
        if eks_scaling.get("minSize") == 0 and eks_scaling.get("desiredSize") == 0:
            results["eks_result"] = "already_parked"
        else:
            try:
                eks.update_nodegroup_config(
                    clusterName=cluster_name,
                    nodegroupName=nodegroup_name,
                    scalingConfig={"minSize": 0, "maxSize": max_size, "desiredSize": 0},
                )
                results["eks_result"] = "scaled_to_zero"
            except Exception as exc:  # pylint: disable=broad-except
                results["eks_result"] = f"error: {exc}"

    # 3. Stop RDS PostgreSQL
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

    results["state_before"] = state
    return results


def _unpark_resources(
    eks: Any, rds: Any, ecs: Any, ecs_cluster: str, cluster_name: str, nodegroup_name: str, rds_id: str
) -> dict[str, Any]:
    state = _describe_state(eks, rds, ecs, ecs_cluster, cluster_name, nodegroup_name, rds_id)
    results: dict[str, Any] = {
        "action": "start",
        "rds_result": "noop",
        "eks_result": "noop",
        "ecs_results": {},
    }

    # 1. Start RDS PostgreSQL
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

    # 2. Restore EKS Node Group (if present)
    eks_scaling = state.get("eks", {}).get("scaling_config", {})
    if eks_scaling:
        if int(eks_scaling.get("minSize", 0)) >= 1 and int(eks_scaling.get("desiredSize", 0)) >= 1:
            results["eks_result"] = "already_active"
        else:
            try:
                eks.update_nodegroup_config(
                    clusterName=cluster_name,
                    nodegroupName=nodegroup_name,
                    scalingConfig={"minSize": 1, "maxSize": 2, "desiredSize": 1},
                )
                results["eks_result"] = "restored_to_1_of_2"
            except Exception as exc:  # pylint: disable=broad-except
                results["eks_result"] = f"error: {exc}"

    # 3. Restore ECS Fargate Spot services (desiredCount=1, except ai-worker which is event-driven at 0)
    for svc in state.get("ecs", {}).get("services", []):
        s_name = svc.get("service_name")
        if not s_name:
            continue
        target_desired = 0 if "ai-worker" in s_name else 1
        if svc.get("desired_count", 0) == target_desired:
            results["ecs_results"][s_name] = f"already_at_{target_desired}"
        else:
            try:
                ecs.update_service(cluster=ecs_cluster, service=s_name, desiredCount=target_desired)
                results["ecs_results"][s_name] = f"restored_to_{target_desired}"
            except Exception as exc:  # pylint: disable=broad-except
                results["ecs_results"][s_name] = f"error: {exc}"

    results["state_before"] = state
    return results


def lambda_handler(
    event: dict[str, Any] | None,
    context: Any = None,
    *,
    eks_client: Any = None,
    rds_client: Any = None,
    ecs_client: Any = None,
) -> dict[str, Any]:
    """Entry point for FinOps Manager Lambda supporting stop, start, status, and audit actions."""
    payload = event or {}
    if isinstance(payload.get("body"), str):
        payload = json.loads(payload["body"])

    action = str(payload.get("action", "status")).strip().lower()
    region, ecs_cluster, cluster_name, nodegroup_name, rds_id = _get_config()
    eks, rds, ecs = _get_clients(region, eks_client=eks_client, rds_client=rds_client, ecs_client=ecs_client)

    if action == "status":
        body: dict[str, Any] = {
            "action": "status",
            **_describe_state(eks, rds, ecs, ecs_cluster, cluster_name, nodegroup_name, rds_id),
        }
    elif action == "audit":
        state = _describe_state(eks, rds, ecs, ecs_cluster, cluster_name, nodegroup_name, rds_id)
        body = _audit_resources(state)
    elif action == "stop":
        body = _park_resources(eks, rds, ecs, ecs_cluster, cluster_name, nodegroup_name, rds_id)
    elif action == "start":
        body = _unpark_resources(eks, rds, ecs, ecs_cluster, cluster_name, nodegroup_name, rds_id)
    else:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"Unsupported action '{action}'. Expected stop, start, status, or audit."}),
        }

    return {"statusCode": 200, "body": json.dumps(body)}
