"""Resolver: the workflow's single terminal step — reached from three
different paths (normal resolution/escalation, an approver rejecting the
action, or a Catch-routed failure), which is why it derives the outcome
from *shape* of the input rather than being told explicitly which path
it's on. Writes the final DynamoDB record and notifies the customer.
"""

import os
import time

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
_dynamodb = boto3.resource("dynamodb")
_sns = boto3.client("sns")

_SESSIONS_TABLE = os.environ["SESSIONS_TABLE_NAME"]
_CUSTOMER_TOPIC_ARN = os.environ["CUSTOMER_NOTIFICATIONS_TOPIC_ARN"]
_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60

_CUSTOMER_MESSAGES = {
    "RESOLVED": "Good news — we detected and resolved your {issue_type} issue automatically.",
    "ESCALATED": "We weren't able to fully resolve your {issue_type} issue remotely, so we've dispatched a technician.",
    "REJECTED": "Your case is on hold — the recommended action needs additional review before we proceed.",
    "FAILED": "We hit an unexpected error working on your case. Our team has been notified.",
}


def _resolution_type(state: dict) -> str:
    if "error" in state:
        return "FAILED"
    if state.get("approval", {}).get("approved") is False:
        return "REJECTED"
    return state["outcome"]["resolution_type"]


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    state = dict(event)
    resolution_type = _resolution_type(state)
    now = str(int(time.time()))

    _dynamodb.Table(_SESSIONS_TABLE).update_item(
        Key={"case_id": state["case_id"]},
        UpdateExpression="SET #status = :status, updated_at = :now, #ttl = :ttl REMOVE task_token",
        ExpressionAttributeNames={"#status": "status", "#ttl": "ttl"},
        ExpressionAttributeValues={
            ":status": resolution_type,
            ":now": now,
            ":ttl": int(time.time()) + _SESSION_TTL_SECONDS,
        },
    )

    message = _CUSTOMER_MESSAGES[resolution_type].format(issue_type=state["issue_type"])
    _sns.publish(
        TopicArn=_CUSTOMER_TOPIC_ARN,
        Subject=f"[SmartHelp] Update on your case {state['case_id']}",
        Message=message,
    )

    logger.info("case resolved", extra={"case_id": state["case_id"], "resolution_type": resolution_type})
    return {"case_id": state["case_id"], "resolution_type": resolution_type}
