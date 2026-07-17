import importlib
import json

import boto3
import pytest
from moto import mock_aws

import starter


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

        ssm = boto3.client("ssm", region_name="us-east-1")
        ssm.put_parameter(Name="/telco-support/test/config/max_diagnostic_attempts", Value="2", Type="String")

        importlib.reload(starter)  # module-level dynamodb/sfn/ssm clients need the mock (and real ARNs) active

        yield table, sfn


def _sqs_event(case: dict) -> dict:
    return {"Records": [{"body": json.dumps(case)}]}


def _case(case_id: str = "case-1") -> dict:
    return {
        "case_id": case_id,
        "customer_id": "cust-123",
        "issue_type": "modem_offline",
        "submitted_at": "2026-07-17T00:00:00Z",
    }


def test_starts_execution_and_writes_session(aws, lambda_context):
    table, sfn = aws

    starter.lambda_handler(_sqs_event(_case()), lambda_context)

    item = table.get_item(Key={"case_id": "case-1"})["Item"]
    assert item["status"] == "IN_PROGRESS"
    assert item["attempt"] == 1

    executions = sfn.list_executions(stateMachineArn=starter._STATE_MACHINE_ARN)["executions"]
    assert len(executions) == 1
    assert executions[0]["name"] == "case-1"


def test_duplicate_delivery_is_a_no_op(aws, lambda_context):
    table, sfn = aws
    event = _sqs_event(_case())

    starter.lambda_handler(event, lambda_context)
    starter.lambda_handler(event, lambda_context)  # simulates SQS at-least-once redelivery

    executions = sfn.list_executions(stateMachineArn=starter._STATE_MACHINE_ARN)["executions"]
    assert len(executions) == 1  # StartExecution was only ever effective once

    item = table.get_item(Key={"case_id": "case-1"})["Item"]
    assert item["attempt"] == 1  # not double-written
