import importlib

import boto3
import pytest
from moto import mock_aws

import resolver


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
        table.put_item(Item={"case_id": "case-1", "status": "PENDING_APPROVAL", "task_token": "abc"})

        sns = boto3.client("sns", region_name="us-east-1")
        topic_arn = sns.create_topic(Name="telco-support-test-customer-notifications")["TopicArn"]
        monkeypatch.setenv("CUSTOMER_NOTIFICATIONS_TOPIC_ARN", topic_arn)

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="telco-support-test-analytics")

        importlib.reload(resolver)  # module-level dynamodb/sns/s3 clients need the mock (and the real topic ARN) active

        yield table, s3


def test_resolved_outcome_is_written_and_customer_notified(aws, lambda_context):
    table, s3 = aws
    event = {
        "case_id": "case-1",
        "customer_id": "cust-123",
        "issue_type": "modem_offline",
        "attempt": 1,
        "decision": {"recommended_action": "REBOOT", "network_impacting": True},
        "outcome": {"resolved": True, "resolution_type": "RESOLVED"},
    }

    result = resolver.lambda_handler(event, lambda_context)

    assert result == {"case_id": "case-1", "resolution_type": "RESOLVED"}
    item = table.get_item(Key={"case_id": "case-1"})["Item"]
    assert item["status"] == "RESOLVED"
    assert "task_token" not in item  # cleaned up now that the workflow has ended

    objects = s3.list_objects_v2(Bucket="telco-support-test-analytics", Prefix="resolutions/")["Contents"]
    assert len(objects) == 1
    assert objects[0]["Key"].endswith("case-1.json")


def test_rejected_approval_is_derived_from_approval_flag(aws, lambda_context):
    event = {
        "case_id": "case-1",
        "customer_id": "cust-123",
        "issue_type": "modem_offline",
        "decision": {"recommended_action": "REBOOT", "network_impacting": True},
        "approval": {"approved": False},
    }

    result = resolver.lambda_handler(event, lambda_context)

    assert result["resolution_type"] == "REJECTED"


def test_failure_is_derived_from_error_key(aws, lambda_context):
    event = {
        "case_id": "case-1",
        "customer_id": "cust-123",
        "issue_type": "modem_offline",
        "error": {"Error": "States.TaskFailed", "Cause": "boom"},
    }

    result = resolver.lambda_handler(event, lambda_context)

    assert result["resolution_type"] == "FAILED"
