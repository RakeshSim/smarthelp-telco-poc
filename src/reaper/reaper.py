"""Scheduled reaper (EventBridge rate rule): reconciles DynamoDB session
records that have drifted out of sync with their Step Functions
execution. This runs independently of any single execution, which is the
whole point — it catches what a workflow's own Retry/Catch blocks can't,
because those only fire while the execution is still alive to run them.

Two situations it looks for, among sessions stale longer than
REAPER_STALE_AFTER_MINUTES:
  1. DynamoDB still says IN_PROGRESS/PENDING_APPROVAL, but the Step
     Functions execution isn't RUNNING anymore — aborted, manually
     stopped, or otherwise died without its own Resolver step running.
     Force-resolved to EXPIRED so it doesn't sit stuck forever.
  2. DynamoDB says PENDING_APPROVAL and the execution IS still RUNNING,
     but nobody has approved/rejected it in a long time. Left alone (the
     workflow's own 24h waitForTaskToken TimeoutSeconds is the real
     backstop), but a reminder notification goes out.
"""

import os
import time
from datetime import UTC, datetime, timedelta

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.dynamodb.conditions import Attr

logger = Logger()
_dynamodb = boto3.resource("dynamodb")
_sfn = boto3.client("stepfunctions")
_sns = boto3.client("sns")

_SESSIONS_TABLE = os.environ["SESSIONS_TABLE_NAME"]
_STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]
_OPS_APPROVAL_TOPIC_ARN = os.environ["OPS_APPROVAL_TOPIC_ARN"]
_CUSTOMER_TOPIC_ARN = os.environ["CUSTOMER_NOTIFICATIONS_TOPIC_ARN"]
_STALE_AFTER_MINUTES = int(os.environ["REAPER_STALE_AFTER_MINUTES"])

_STUCK_STATUSES = ["IN_PROGRESS", "PENDING_APPROVAL"]
_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


def _execution_arn(case_id: str) -> str:
    # Standard Step Functions execution ARNs are deterministic from the
    # state machine ARN + execution name (== case_id here) — no need to
    # list/search executions to find the right one.
    return _STATE_MACHINE_ARN.replace(":stateMachine:", ":execution:") + f":{case_id}"


def _is_execution_running(case_id: str) -> bool:
    try:
        status = _sfn.describe_execution(executionArn=_execution_arn(case_id))["status"]
    except _sfn.exceptions.ExecutionDoesNotExist:
        return False
    return status == "RUNNING"


def _reconcile(item: dict) -> None:
    case_id = item["case_id"]

    if _is_execution_running(case_id):
        if item["status"] == "PENDING_APPROVAL":
            _sns.publish(
                TopicArn=_OPS_APPROVAL_TOPIC_ARN,
                Subject=f"[SmartHelp POC] REMINDER: case {case_id} still awaiting approval",
                Message=f"Case {case_id} has been PENDING_APPROVAL for over {_STALE_AFTER_MINUTES} minutes.",
            )
            logger.info("sent approval reminder", extra={"case_id": case_id})
        return

    now = int(time.time())
    _dynamodb.Table(_SESSIONS_TABLE).update_item(
        Key={"case_id": case_id},
        UpdateExpression="SET #status = :status, updated_at = :now, #ttl = :ttl REMOVE task_token",
        ExpressionAttributeNames={"#status": "status", "#ttl": "ttl"},
        ExpressionAttributeValues={
            ":status": "EXPIRED",
            ":now": now,
            ":ttl": now + _SESSION_TTL_SECONDS,
        },
    )
    _sns.publish(
        TopicArn=_CUSTOMER_TOPIC_ARN,
        Subject=f"[SmartHelp] Update on your case {case_id}",
        Message="We're sorry — we ran into an issue working on your case. Our team is following up separately.",
    )
    logger.warning("reconciled orphaned session", extra={"case_id": case_id, "previous_status": item["status"]})


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    cutoff = int((datetime.now(UTC) - timedelta(minutes=_STALE_AFTER_MINUTES)).timestamp())
    table = _dynamodb.Table(_SESSIONS_TABLE)

    # Small, demo-scale table — a Scan is fine here. At real production
    # volume this would use a GSI on `status` (or `status`+`updated_at`)
    # so the reaper queries instead of scanning the whole table.
    scan_kwargs = {"FilterExpression": Attr("status").is_in(_STUCK_STATUSES) & Attr("updated_at").lt(cutoff)}
    reconciled = 0
    while True:
        response = table.scan(**scan_kwargs)
        for item in response["Items"]:
            _reconcile(item)
            reconciled += 1
        if "LastEvaluatedKey" not in response:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    logger.info("reaper pass complete", extra={"reconciled": reconciled})
    return {"reconciled": reconciled}
