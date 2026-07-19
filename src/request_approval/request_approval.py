"""Human-approval gate: the Task this Lambda backs uses Step Functions'
`lambda:invoke.waitForTaskToken` integration, so the *workflow* pauses here
until something outside this Lambda calls SendTaskSuccess/SendTaskFailure
with the token below — this function's own return value is not what
resumes the execution.

Two responsibilities while paused:
  1. Persist the task token to DynamoDB, keyed by case_id, so whatever
     resumes the workflow (a human, an approval API/UI, this repo's demo
     CLI command) can look it up without needing to inspect the running
     Step Functions execution directly.
  2. Publish an SNS notification an approver would actually see, telling
     them what's pending and how to approve/reject it.

No approval API exists in this POC on purpose — approving via the AWS CLI
(`aws stepfunctions send-task-success`) demonstrates the same
human-in-the-loop mechanics without building a second Lambda + API route
whose interesting content would just be "call SendTaskSuccess."
"""

import json
import os
import time

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
_dynamodb = boto3.resource("dynamodb")
_sns = boto3.client("sns")

_SESSIONS_TABLE = os.environ["SESSIONS_TABLE_NAME"]
_OPS_APPROVAL_TOPIC_ARN = os.environ["OPS_APPROVAL_TOPIC_ARN"]


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event: dict, context: LambdaContext) -> None:
    task_token = event["TaskToken"]
    case = event["input"]
    case_id = case["case_id"]
    recommended_action = case["decision"]["recommended_action"]

    _dynamodb.Table(_SESSIONS_TABLE).update_item(
        Key={"case_id": case_id},
        UpdateExpression="SET #status = :status, task_token = :token, updated_at = :now",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "PENDING_APPROVAL",
            ":token": task_token,
            ":now": int(time.time()),
        },
    )

    message = (
        f"Case {case_id} (customer {case['customer_id']}, issue: {case['issue_type']}) "
        f"needs approval for a network-impacting action: {recommended_action}.\n\n"
        f"Diagnostics: {json.dumps(case['diagnostics'])}\n\n"
        "To approve or reject, fetch the task token and call SendTaskSuccess — "
        "see README 'Demo: approving a pending case'."
    )

    _sns.publish(
        TopicArn=_OPS_APPROVAL_TOPIC_ARN,
        Subject=f"[SmartHelp POC] Approval needed for case {case_id}",
        Message=message,
    )

    logger.info(
        "approval requested, workflow paused", extra={"case_id": case_id, "recommended_action": recommended_action}
    )
