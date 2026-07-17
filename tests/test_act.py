import importlib
import json

import boto3
import pytest
from moto import mock_aws

import act


@pytest.fixture
def dispatch_secret():
    with mock_aws():
        client = boto3.client("secretsmanager", region_name="us-east-1")
        client.create_secret(Name="telco-support-test-dispatch", SecretString=json.dumps({"api_key": "mock-key-123"}))

        importlib.reload(act)  # module-level secretsmanager client needs the mock active

        yield


def _event(recommended_action: str, attempt: int = 1) -> dict:
    return {
        "case_id": "case-1",
        "attempt": attempt,
        "decision": {"recommended_action": recommended_action, "network_impacting": recommended_action != "NONE"},
    }


def test_none_action_is_a_no_op(dispatch_secret, lambda_context):
    result = act.lambda_handler(_event("NONE"), lambda_context)

    assert result["action_result"] == {"action_taken": "NONE", "success": True}


def test_dispatch_fetches_secret_and_creates_a_ticket(dispatch_secret, lambda_context):
    result = act.lambda_handler(_event("DISPATCH"), lambda_context)

    assert result["action_result"]["action_taken"] == "DISPATCH"
    assert result["action_result"]["success"] is True
    assert result["action_result"]["ticket_id"].startswith("TCK-")
    assert act._dispatch_api_key_cache == "mock-key-123"


def test_reboot_result_is_deterministic_per_case_and_attempt(dispatch_secret, lambda_context):
    first = act.lambda_handler(_event("REBOOT", attempt=1), lambda_context)
    second = act.lambda_handler(_event("REBOOT", attempt=1), lambda_context)

    assert first["action_result"] == second["action_result"]
