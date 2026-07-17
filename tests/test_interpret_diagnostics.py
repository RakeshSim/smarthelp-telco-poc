import importlib

import boto3
import pytest
from moto import mock_aws

import interpret_diagnostics


@pytest.fixture
def sessions_table():
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="telco-support-test-sessions",
            KeySchema=[{"AttributeName": "case_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "case_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.put_item(Item={"case_id": "case-1", "status": "IN_PROGRESS"})

        # interpret_diagnostics.py builds its DynamoDB client at module
        # scope, imported (at collection time) before this mock was
        # active — reload so it picks up the mocked AWS backend.
        importlib.reload(interpret_diagnostics)

        yield table


def _event(issue_type: str, diagnostics: dict, attempt: int) -> dict:
    return {
        "case_id": "case-1",
        "customer_id": "cust-123",
        "issue_type": issue_type,
        "attempt": attempt,
        "max_attempts": 2,
        "diagnostics": diagnostics,
    }


def test_no_signal_first_attempt_recommends_reboot(sessions_table, lambda_context):
    event = _event("modem_offline", {"error_codes": ["NO_SIGNAL"], "packet_loss_pct": 100.0}, attempt=1)

    result = interpret_diagnostics.lambda_handler(event, lambda_context)

    assert result["decision"] == {"recommended_action": "REBOOT", "network_impacting": True}


def test_still_severe_on_second_attempt_recommends_dispatch(sessions_table, lambda_context):
    event = _event("modem_offline", {"error_codes": ["NO_SIGNAL"], "packet_loss_pct": 100.0}, attempt=2)

    result = interpret_diagnostics.lambda_handler(event, lambda_context)

    assert result["decision"] == {"recommended_action": "DISPATCH", "network_impacting": True}


def test_minor_issue_needs_no_action(sessions_table, lambda_context):
    event = _event("slow_speeds", {"error_codes": [], "packet_loss_pct": 3.0}, attempt=1)

    result = interpret_diagnostics.lambda_handler(event, lambda_context)

    assert result["decision"] == {"recommended_action": "NONE", "network_impacting": False}


def test_preserves_original_state_fields(sessions_table, lambda_context):
    event = _event("modem_offline", {"error_codes": ["NO_SIGNAL"], "packet_loss_pct": 100.0}, attempt=1)

    result = interpret_diagnostics.lambda_handler(event, lambda_context)

    assert result["case_id"] == "case-1"
    assert result["customer_id"] == "cust-123"
    assert result["diagnostics"] == event["diagnostics"]
