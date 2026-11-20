"""Unit tests for FinOps Manager Lambda handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.finops_manager.handler import lambda_handler


def _mock_clients(
    ng_min: int = 1,
    ng_desired: int = 1,
    ng_max: int = 2,
    rds_status: str = "available",
    ecs_services: list[dict] | None = None,
):
    eks = MagicMock()
    rds = MagicMock()
    ecs = MagicMock()

    eks.describe_nodegroup.return_value = {
        "nodegroup": {
            "status": "ACTIVE",
            "scalingConfig": {"minSize": ng_min, "maxSize": ng_max, "desiredSize": ng_desired},
        }
    }
    rds.describe_db_instances.return_value = {
        "DBInstances": [{"DBInstanceStatus": rds_status, "DBInstanceClass": "db.t4g.micro"}]
    }

    if ecs_services is None:
        ecs_services = [
            {"serviceName": "pfm-core-ledger-java", "status": "ACTIVE", "desiredCount": 1, "runningCount": 1},
            {"serviceName": "pfm-ingestion-bff-go", "status": "ACTIVE", "desiredCount": 1, "runningCount": 1},
            {"serviceName": "pfm-ai-worker-python", "status": "ACTIVE", "desiredCount": 0, "runningCount": 0},
        ]

    ecs.list_services.return_value = {
        "serviceArns": [f"arn:aws:ecs:us-east-2:123456789012:service/pfm-pilot-prod/{s['serviceName']}" for s in ecs_services]
    }
    ecs.describe_services.return_value = {"services": ecs_services}

    return eks, rds, ecs


def test_status_returns_ecs_eks_and_rds_state():
    eks, rds, ecs = _mock_clients(ng_min=1, ng_desired=1, ng_max=2, rds_status="available")
    resp = lambda_handler({"action": "status"}, eks_client=eks, rds_client=rds, ecs_client=ecs)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["action"] == "status"
    assert len(body["ecs"]["services"]) == 3
    assert body["eks"]["status"] == "ACTIVE"
    assert body["rds"]["status"] == "available"


def test_audit_returns_consolidated_report():
    eks, rds, ecs = _mock_clients(ng_min=1, ng_desired=1, ng_max=2, rds_status="available")
    resp = lambda_handler({"action": "audit"}, eks_client=eks, rds_client=rds, ecs_client=ecs)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["action"] == "audit"
    assert body["active_resources_count"] >= 3
    assert body["monthly_run_rate_estimate_usd"] > 0
    assert any("pfm-core-ledger-java" in r for r in body["active_resources"])
    assert any("pfm-ai-worker-python" in r for r in body["stopped_resources"])


def test_stop_parks_ecs_eks_and_rds():
    eks, rds, ecs = _mock_clients(ng_min=1, ng_desired=1, ng_max=2, rds_status="available")
    resp = lambda_handler({"action": "stop"}, eks_client=eks, rds_client=rds, ecs_client=ecs)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["eks_result"] == "scaled_to_zero"
    assert body["rds_result"] == "stopping"
    assert body["ecs_results"]["pfm-core-ledger-java"] == "scaled_to_zero"
    assert body["ecs_results"]["pfm-ai-worker-python"] == "already_zero"

    eks.update_nodegroup_config.assert_called_once_with(
        clusterName="pfm-eks-prod",
        nodegroupName="pfm-eks-prod-graviton-mvp",
        scalingConfig={"minSize": 0, "maxSize": 2, "desiredSize": 0},
    )
    rds.stop_db_instance.assert_called_once_with(DBInstanceIdentifier="pfm-core-ledger-prod")
    ecs.update_service.assert_any_call(
        cluster="pfm-pilot-prod", service="pfm-core-ledger-java", desiredCount=0
    )


def test_stop_is_idempotent_when_already_parked():
    eks, rds, ecs = _mock_clients(
        ng_min=0,
        ng_desired=0,
        ng_max=2,
        rds_status="stopped",
        ecs_services=[
            {"serviceName": "pfm-core-ledger-java", "status": "ACTIVE", "desiredCount": 0, "runningCount": 0}
        ],
    )
    resp = lambda_handler({"action": "stop"}, eks_client=eks, rds_client=rds, ecs_client=ecs)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["eks_result"] == "already_parked"
    assert body["rds_result"] == "already_stopped"
    assert body["ecs_results"]["pfm-core-ledger-java"] == "already_zero"
    eks.update_nodegroup_config.assert_not_called()
    rds.stop_db_instance.assert_not_called()
    ecs.update_service.assert_not_called()


def test_start_unparks_rds_eks_and_ecs():
    eks, rds, ecs = _mock_clients(
        ng_min=0,
        ng_desired=0,
        ng_max=2,
        rds_status="stopped",
        ecs_services=[
            {"serviceName": "pfm-core-ledger-java", "status": "ACTIVE", "desiredCount": 0, "runningCount": 0},
            {"serviceName": "pfm-ai-worker-python", "status": "ACTIVE", "desiredCount": 0, "runningCount": 0},
        ],
    )
    resp = lambda_handler({"action": "start"}, eks_client=eks, rds_client=rds, ecs_client=ecs)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["rds_result"] == "starting"
    assert body["eks_result"] == "restored_to_1_of_2"
    assert body["ecs_results"]["pfm-core-ledger-java"] == "restored_to_1"
    assert body["ecs_results"]["pfm-ai-worker-python"] == "already_at_0"
    rds.start_db_instance.assert_called_once_with(DBInstanceIdentifier="pfm-core-ledger-prod")
    eks.update_nodegroup_config.assert_called_once_with(
        clusterName="pfm-eks-prod",
        nodegroupName="pfm-eks-prod-graviton-mvp",
        scalingConfig={"minSize": 1, "maxSize": 2, "desiredSize": 1},
    )
    ecs.update_service.assert_called_once_with(
        cluster="pfm-pilot-prod", service="pfm-core-ledger-java", desiredCount=1
    )


def test_unsupported_action_returns_400():
    eks, rds, ecs = _mock_clients()
    resp = lambda_handler({"action": "destroy"}, eks_client=eks, rds_client=rds, ecs_client=ecs)
    assert resp["statusCode"] == 400
