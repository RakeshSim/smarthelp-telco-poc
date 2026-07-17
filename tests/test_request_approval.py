import importlib

import boto3
import pytest
from moto import mock_aws

import request_approval


@pytest.fixture
def aws(monkeypatch):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="telco-support-test-sessions",
            KeySchema=[{"AttributeName": "case_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "case_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.put_item(Item={"case_id": "case-1", "status": "IN_PROGRESS"})

        sns = boto3.client("sns", region_name="us-east-1")
        topic_arn = sns.create_topic(Name="telco-support-test-ops-approval")["TopicArn"]
        monkeypatch.setenv("OPS_APPROVAL_TOPIC_ARN", topic_arn)

        importlib.reload(request_approval)

        yield table


def test_persists_task_token_and_pauses(aws, lambda_context):
    event = {
        "TaskToken": "test-token-abc",
        "input": {
            "case_id": "case-1",
            "customer_id": "cust-123",
            "issue_type": "modem_offline",
            "decision": {"recommended_action": "REBOOT", "network_impacting": True},
            "diagnostics": {"error_codes": ["NO_SIGNAL"]},
        },
    }

    request_approval.lambda_handler(event, lambda_context)

    item = aws.get_item(Key={"case_id": "case-1"})["Item"]
    assert item["status"] == "PENDING_APPROVAL"
    assert item["task_token"] == "test-token-abc"
