import importlib
import json
import time

import boto3
import pytest
from moto import mock_aws

import reaper


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

        iam = boto3.client("iam", region_name="us-east-1")
        role_arn = iam.create_role(
            RoleName="sfn-role",
            AssumeRolePolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "states.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                }
            ),
        )["Role"]["Arn"]

        sfn = boto3.client("stepfunctions", region_name="us-east-1")
        definition = json.dumps({"StartAt": "Noop", "States": {"Noop": {"Type": "Pass", "End": True}}})
        state_machine_arn = sfn.create_state_machine(
            name="telco-support-test", definition=definition, roleArn=role_arn
        )["stateMachineArn"]
        monkeypatch.setenv("STATE_MACHINE_ARN", state_machine_arn)

        sns = boto3.client("sns", region_name="us-east-1")
        ops_topic_arn = sns.create_topic(Name="telco-support-test-ops-approval")["TopicArn"]
        customer_topic_arn = sns.create_topic(Name="telco-support-test-customer-notifications")["TopicArn"]
        monkeypatch.setenv("OPS_APPROVAL_TOPIC_ARN", ops_topic_arn)
        monkeypatch.setenv("CUSTOMER_NOTIFICATIONS_TOPIC_ARN", customer_topic_arn)

        importlib.reload(reaper)

        yield table, sfn


def _stale_item(case_id: str, status: str) -> dict:
    return {
        "case_id": case_id,
        "customer_id": "cust-123",
        "issue_type": "modem_offline",
        "status": status,
        "attempt": 1,
        "updated_at": int(time.time()) - 3600,  # an hour ago — well past the 15-minute test threshold
    }


def test_orphaned_session_with_no_execution_is_expired(aws, lambda_context):
    table, sfn = aws
    table.put_item(Item=_stale_item("case-orphan", "PENDING_APPROVAL"))
    # No execution was ever started for this case_id — simulates one that
    # was aborted/manually stopped and never reached its own Resolver step.

    result = reaper.lambda_handler({}, lambda_context)

    assert result == {"reconciled": 1}
    item = table.get_item(Key={"case_id": "case-orphan"})["Item"]
    assert item["status"] == "EXPIRED"
    assert "task_token" not in item


def test_still_running_pending_approval_sends_reminder_and_is_untouched(aws, lambda_context):
    table, sfn = aws
    table.put_item(Item=_stale_item("case-waiting", "PENDING_APPROVAL"))
    sfn.start_execution(stateMachineArn=reaper._STATE_MACHINE_ARN, name="case-waiting", input="{}")

    result = reaper.lambda_handler({}, lambda_context)

    assert result == {"reconciled": 1}
    item = table.get_item(Key={"case_id": "case-waiting"})["Item"]
    assert item["status"] == "PENDING_APPROVAL"  # untouched — still legitimately in flight


def test_fresh_session_is_ignored(aws, lambda_context):
    table, sfn = aws
    fresh = _stale_item("case-fresh", "IN_PROGRESS")
    fresh["updated_at"] = int(time.time())  # just updated, well within the staleness window
    table.put_item(Item=fresh)

    result = reaper.lambda_handler({}, lambda_context)

    assert result == {"reconciled": 0}


def test_resolved_session_is_never_considered(aws, lambda_context):
    table, sfn = aws
    resolved = _stale_item("case-done", "RESOLVED")
    table.put_item(Item=resolved)

    result = reaper.lambda_handler({}, lambda_context)

    assert result == {"reconciled": 0}
