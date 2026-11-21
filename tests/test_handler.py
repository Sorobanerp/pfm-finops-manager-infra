"""Unit tests for FinOps Manager Lambda handler (ECS Fargate Spot + RDS + AI Worker Lambda)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.finops_manager.handler import lambda_handler


def _mock_clients(
    rds_status: str = "available",
    ecs_services: list[dict] | None = None,
    lambda_state: str = "Active",
    reserved_concurrency: int | None = None,
    eks_clusters: list[str] | None = None,
    nat_gateways: list[dict] | None = None,
):
    ecs = MagicMock()
    rds = MagicMock()
    lmb = MagicMock()
    ec2 = MagicMock()
    eks = MagicMock()

    if ecs_services is None:
        ecs_services = [
            {"serviceName": "pfm-core-ledger-java", "status": "ACTIVE", "desiredCount": 1, "runningCount": 1},
            {"serviceName": "pfm-ingestion-bff-go", "status": "ACTIVE", "desiredCount": 1, "runningCount": 1},
            {"serviceName": "pfm-forecast-engine-go", "status": "ACTIVE", "desiredCount": 1, "runningCount": 1},
            {"serviceName": "pfm-web-nextjs", "status": "ACTIVE", "desiredCount": 1, "runningCount": 1},
        ]

    ecs.list_services.return_value = {
        "serviceArns": [
            f"arn:aws:ecs:us-east-2:366476833548:service/pfm-ecs-pilot/{s['serviceName']}"
            for s in ecs_services
        ]
    }
    ecs.describe_services.return_value = {"services": ecs_services}

    rds.describe_db_instances.return_value = {
        "DBInstances": [{"DBInstanceStatus": rds_status, "DBInstanceClass": "db.t4g.micro"}]
    }

    fn_resp = {
        "Configuration": {
            "FunctionName": "pfm-ai-worker-python-prod",
            "FunctionArn": "arn:aws:lambda:us-east-2:366476833548:function:pfm-ai-worker-python-prod",
            "State": lambda_state,
            "Runtime": "python3.12",
        }
    }
    if reserved_concurrency is not None:
        fn_resp["Concurrency"] = {"ReservedConcurrentExecutions": reserved_concurrency}
    lmb.get_function.return_value = fn_resp

    eks.list_clusters.return_value = {"clusters": eks_clusters or []}
    ec2.describe_nat_gateways.return_value = {"NatGateways": nat_gateways or []}

    return ecs, rds, lmb, ec2, eks


def test_status_returns_ecs_rds_and_ai_worker_lambda_state():
    ecs, rds, lmb, ec2, eks = _mock_clients(rds_status="available")
    resp = lambda_handler(
        {"action": "status"},
        ecs_client=ecs,
        rds_client=rds,
        lambda_client=lmb,
        ec2_client=ec2,
        eks_client=eks,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["action"] == "status"
    assert body["ecs"]["cluster_name"] == "pfm-ecs-pilot"
    assert len(body["ecs"]["services"]) == 4
    assert body["rds"]["status"] == "available"
    assert body["rds"]["DBInstanceStatus"] == "available"
    assert body["ai_worker_lambda"]["function_name"] == "pfm-ai-worker-python-prod"
    assert body["ai_worker_lambda"]["state"] == "Active"
    assert body["cost_guardrails"]["alerts"] == []


def test_audit_returns_consolidated_report_and_cost_guardrails():
    ecs, rds, lmb, ec2, eks = _mock_clients(rds_status="available")
    resp = lambda_handler(
        {"action": "audit"},
        ecs_client=ecs,
        rds_client=rds,
        lambda_client=lmb,
        ec2_client=ec2,
        eks_client=eks,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["action"] == "audit"
    assert body["active_resources_count"] == 6
    assert body["stopped_resources_count"] == 0
    assert body["monthly_run_rate_estimate_usd"] == 33.6
    assert body["alerts"] == []
    assert any("pfm-core-ledger-java" in r for r in body["active_resources"])
    assert any("pfm-ai-worker-python-prod" in r for r in body["active_resources"])


def test_audit_raises_alerts_when_eks_or_nat_gateway_detected():
    ecs, rds, lmb, ec2, eks = _mock_clients(
        rds_status="stopped",
        eks_clusters=["rogue-eks"],
        nat_gateways=[{"NatGatewayId": "nat-0123456789abcdef0"}],
    )
    resp = lambda_handler(
        {"action": "audit"},
        ecs_client=ecs,
        rds_client=rds,
        lambda_client=lmb,
        ec2_client=ec2,
        eks_client=eks,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["alerts"]) == 2
    assert any("EKS" in a for a in body["alerts"])
    assert any("NAT Gateways" in a for a in body["alerts"])


def test_stop_parks_ecs_and_rds_without_freezing_lambda_by_default():
    ecs, rds, lmb, ec2, eks = _mock_clients(rds_status="available")
    resp = lambda_handler(
        {"action": "stop"},
        ecs_client=ecs,
        rds_client=rds,
        lambda_client=lmb,
        ec2_client=ec2,
        eks_client=eks,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["rds_result"] == "stopping"
    assert body["ecs_results"]["pfm-core-ledger-java"] == "scaled_to_zero"
    assert body["ecs_results"]["pfm-ingestion-bff-go"] == "scaled_to_zero"
    assert body["ecs_results"]["pfm-forecast-engine-go"] == "scaled_to_zero"
    assert body["ecs_results"]["pfm-web-nextjs"] == "scaled_to_zero"
    assert body["lambda_result"] == "idle_zero_cost_no_freeze"

    rds.stop_db_instance.assert_called_once_with(DBInstanceIdentifier="pfm-core-ledger-prod")
    ecs.update_service.assert_any_call(
        cluster="pfm-ecs-pilot", service="pfm-core-ledger-java", desiredCount=0
    )
    lmb.put_function_concurrency.assert_not_called()


def test_stop_freezes_lambda_concurrency_when_requested():
    ecs, rds, lmb, ec2, eks = _mock_clients(rds_status="available")
    resp = lambda_handler(
        {"action": "stop", "freeze_lambda": True},
        ecs_client=ecs,
        rds_client=rds,
        lambda_client=lmb,
        ec2_client=ec2,
        eks_client=eks,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["lambda_result"] == "frozen_concurrency_0"
    lmb.put_function_concurrency.assert_called_once_with(
        FunctionName="pfm-ai-worker-python-prod",
        ReservedConcurrentExecutions=0,
    )


def test_stop_is_idempotent_when_already_parked():
    ecs, rds, lmb, ec2, eks = _mock_clients(
        rds_status="stopped",
        ecs_services=[
            {"serviceName": "pfm-core-ledger-java", "status": "ACTIVE", "desiredCount": 0, "runningCount": 0}
        ],
    )
    resp = lambda_handler(
        {"action": "stop"},
        ecs_client=ecs,
        rds_client=rds,
        lambda_client=lmb,
        ec2_client=ec2,
        eks_client=eks,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["rds_result"] == "already_stopped"
    assert body["ecs_results"]["pfm-core-ledger-java"] == "already_zero"
    rds.stop_db_instance.assert_not_called()
    ecs.update_service.assert_not_called()


def test_start_unparks_rds_ecs_and_unfreezes_lambda():
    ecs, rds, lmb, ec2, eks = _mock_clients(
        rds_status="stopped",
        reserved_concurrency=0,
        ecs_services=[
            {"serviceName": "pfm-core-ledger-java", "status": "ACTIVE", "desiredCount": 0, "runningCount": 0},
            {"serviceName": "pfm-ingestion-bff-go", "status": "ACTIVE", "desiredCount": 0, "runningCount": 0},
        ],
    )
    resp = lambda_handler(
        {"action": "start"},
        ecs_client=ecs,
        rds_client=rds,
        lambda_client=lmb,
        ec2_client=ec2,
        eks_client=eks,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["rds_result"] == "starting"
    assert body["ecs_results"]["pfm-core-ledger-java"] == "restored_to_1"
    assert body["ecs_results"]["pfm-ingestion-bff-go"] == "restored_to_1"
    assert body["lambda_result"] == "concurrency_unfrozen"

    rds.start_db_instance.assert_called_once_with(DBInstanceIdentifier="pfm-core-ledger-prod")
    ecs.update_service.assert_any_call(
        cluster="pfm-ecs-pilot", service="pfm-core-ledger-java", desiredCount=1
    )
    lmb.delete_function_concurrency.assert_called_once_with(
        FunctionName="pfm-ai-worker-python-prod"
    )


def test_unsupported_action_returns_400():
    ecs, rds, lmb, ec2, eks = _mock_clients()
    resp = lambda_handler(
        {"action": "destroy"},
        ecs_client=ecs,
        rds_client=rds,
        lambda_client=lmb,
        ec2_client=ec2,
        eks_client=eks,
    )
    assert resp["statusCode"] == 400
