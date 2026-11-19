"""PFM FinOps Manager AWS Lambda handler (Park 20:30 BRT / Unpark 06:00 BRT)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


def _get_config() -> tuple[str, str, str, str]:
    region = os.environ.get("AWS_REGION", "us-east-2")
    cluster_name = os.environ.get("EKS_CLUSTER_NAME", "pfm-eks-prod")
    nodegroup_name = os.environ.get("EKS_NODEGROUP_NAME", "pfm-eks-prod-graviton-mvp")
    rds_identifier = os.environ.get("RDS_INSTANCE_ID", "pfm-core-ledger-prod")
    return region, cluster_name, nodegroup_name, rds_identifier


def _get_clients(region: str, eks_client: Any = None, rds_client: Any = None) -> tuple[Any, Any]:
    if eks_client is not None and rds_client is not None:
        return eks_client, rds_client
    import boto3

    eks = eks_client or boto3.client("eks", region_name=region)
    rds = rds_client or boto3.client("rds", region_name=region)
    return eks, rds


def _describe_state(eks: Any, rds: Any, cluster_name: str, nodegroup_name: str, rds_id: str) -> dict[str, Any]:
    ng_resp = eks.describe_nodegroup(clusterName=cluster_name, nodegroupName=nodegroup_name)["nodegroup"]
    rds_resp = rds.describe_db_instances(DBInstanceIdentifier=rds_id)["DBInstances"][0]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "eks": {
            "cluster_name": cluster_name,
            "nodegroup_name": nodegroup_name,
            "status": ng_resp.get("status"),
            "scaling_config": ng_resp.get("scalingConfig", {}),
        },
        "rds": {
            "db_instance_identifier": rds_id,
            "status": rds_resp.get("DBInstanceStatus"),
            "instance_class": rds_resp.get("DBInstanceClass"),
        },
    }


def _park_resources(eks: Any, rds: Any, cluster_name: str, nodegroup_name: str, rds_id: str) -> dict[str, Any]:
    state = _describe_state(eks, rds, cluster_name, nodegroup_name, rds_id)
    results: dict[str, Any] = {"action": "stop", "eks_result": "noop", "rds_result": "noop"}

    scaling = state["eks"]["scaling_config"]
    max_size = max(int(scaling.get("maxSize", 2)), 1)
    if scaling.get("minSize") == 0 and scaling.get("desiredSize") == 0:
        results["eks_result"] = "already_parked"
    else:
        eks.update_nodegroup_config(
            clusterName=cluster_name,
            nodegroupName=nodegroup_name,
            scalingConfig={"minSize": 0, "maxSize": max_size, "desiredSize": 0},
        )
        results["eks_result"] = "scaled_to_zero"

    rds_status = state["rds"]["status"]
    if rds_status == "available":
        rds.stop_db_instance(DBInstanceIdentifier=rds_id)
        results["rds_result"] = "stopping"
    elif rds_status in {"stopped", "stopping"}:
        results["rds_result"] = f"already_{rds_status}"
    else:
        results["rds_result"] = f"skipped_status_{rds_status}"

    results["state_before"] = state
    return results


def _unpark_resources(eks: Any, rds: Any, cluster_name: str, nodegroup_name: str, rds_id: str) -> dict[str, Any]:
    state = _describe_state(eks, rds, cluster_name, nodegroup_name, rds_id)
    results: dict[str, Any] = {"action": "start", "rds_result": "noop", "eks_result": "noop"}

    rds_status = state["rds"]["status"]
    if rds_status == "stopped":
        rds.start_db_instance(DBInstanceIdentifier=rds_id)
        results["rds_result"] = "starting"
    elif rds_status in {"available", "starting"}:
        results["rds_result"] = f"already_{rds_status}"
    else:
        results["rds_result"] = f"skipped_status_{rds_status}"

    scaling = state["eks"]["scaling_config"]
    if int(scaling.get("minSize", 0)) >= 1 and int(scaling.get("desiredSize", 0)) >= 1:
        results["eks_result"] = "already_active"
    else:
        eks.update_nodegroup_config(
            clusterName=cluster_name,
            nodegroupName=nodegroup_name,
            scalingConfig={"minSize": 1, "maxSize": 2, "desiredSize": 1},
        )
        results["eks_result"] = "restored_to_1_of_2"

    results["state_before"] = state
    return results


def lambda_handler(event: dict[str, Any] | None, context: Any = None, *, eks_client: Any = None, rds_client: Any = None) -> dict[str, Any]:
    """Entry point for FinOps Manager Lambda supporting stop, start, and status actions."""
    payload = event or {}
    if isinstance(payload.get("body"), str):
        payload = json.loads(payload["body"])

    action = str(payload.get("action", "status")).strip().lower()
    region, cluster_name, nodegroup_name, rds_id = _get_config()
    eks, rds = _get_clients(region, eks_client=eks_client, rds_client=rds_client)

    if action == "status":
        body: dict[str, Any] = {"action": "status", **_describe_state(eks, rds, cluster_name, nodegroup_name, rds_id)}
    elif action == "stop":
        body = _park_resources(eks, rds, cluster_name, nodegroup_name, rds_id)
    elif action == "start":
        body = _unpark_resources(eks, rds, cluster_name, nodegroup_name, rds_id)
    else:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"Unsupported action '{action}'. Expected stop, start, or status."}),
        }

    return {"statusCode": 200, "body": json.dumps(body)}
