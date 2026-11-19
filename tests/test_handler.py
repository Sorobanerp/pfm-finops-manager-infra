"""Unit tests for FinOps Manager Lambda handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.finops_manager.handler import lambda_handler


def _mock_clients(ng_min: int = 1, ng_desired: int = 1, ng_max: int = 2, rds_status: str = "available"):
    eks = MagicMock()
    rds = MagicMock()
    eks.describe_nodegroup.return_value = {
        "nodegroup": {
            "status": "ACTIVE",
            "scalingConfig": {"minSize": ng_min, "maxSize": ng_max, "desiredSize": ng_desired},
        }
    }
    rds.describe_db_instances.return_value = {
        "DBInstances": [{"DBInstanceStatus": rds_status, "DBInstanceClass": "db.t4g.micro"}]
    }
    return eks, rds


def test_status_returns_eks_and_rds_state():
    eks, rds = _mock_clients(ng_min=1, ng_desired=1, ng_max=2, rds_status="available")
    resp = lambda_handler({"action": "status"}, eks_client=eks, rds_client=rds)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["action"] == "status"
    assert body["eks"]["status"] == "ACTIVE"
    assert body["rds"]["status"] == "available"


def test_stop_parks_eks_and_rds():
    eks, rds = _mock_clients(ng_min=1, ng_desired=1, ng_max=2, rds_status="available")
    resp = lambda_handler({"action": "stop"}, eks_client=eks, rds_client=rds)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["eks_result"] == "scaled_to_zero"
    assert body["rds_result"] == "stopping"
    eks.update_nodegroup_config.assert_called_once_with(
        clusterName="pfm-eks-prod",
        nodegroupName="pfm-eks-prod-graviton-mvp",
        scalingConfig={"minSize": 0, "maxSize": 2, "desiredSize": 0},
    )
    rds.stop_db_instance.assert_called_once_with(DBInstanceIdentifier="pfm-core-ledger-prod")


def test_stop_is_idempotent_when_already_parked():
    eks, rds = _mock_clients(ng_min=0, ng_desired=0, ng_max=2, rds_status="stopped")
    resp = lambda_handler({"action": "stop"}, eks_client=eks, rds_client=rds)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["eks_result"] == "already_parked"
    assert body["rds_result"] == "already_stopped"
    eks.update_nodegroup_config.assert_not_called()
    rds.stop_db_instance.assert_not_called()


def test_start_unparks_rds_and_eks():
    eks, rds = _mock_clients(ng_min=0, ng_desired=0, ng_max=2, rds_status="stopped")
    resp = lambda_handler({"action": "start"}, eks_client=eks, rds_client=rds)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["rds_result"] == "starting"
    assert body["eks_result"] == "restored_to_1_of_2"
    rds.start_db_instance.assert_called_once_with(DBInstanceIdentifier="pfm-core-ledger-prod")
    eks.update_nodegroup_config.assert_called_once_with(
        clusterName="pfm-eks-prod",
        nodegroupName="pfm-eks-prod-graviton-mvp",
        scalingConfig={"minSize": 1, "maxSize": 2, "desiredSize": 1},
    )


def test_start_is_idempotent_when_already_running():
    eks, rds = _mock_clients(ng_min=1, ng_desired=1, ng_max=2, rds_status="available")
    resp = lambda_handler({"action": "start"}, eks_client=eks, rds_client=rds)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["rds_result"] == "already_available"
    assert body["eks_result"] == "already_active"
    rds.start_db_instance.assert_not_called()
    eks.update_nodegroup_config.assert_not_called()


def test_unsupported_action_returns_400():
    eks, rds = _mock_clients()
    resp = lambda_handler({"action": "destroy"}, eks_client=eks, rds_client=rds)
    assert resp["statusCode"] == 400
