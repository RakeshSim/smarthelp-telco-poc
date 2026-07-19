"""Interpret Diagnostics" step: rule-based decision on what to do next.

Simple, explainable if/elif rules rather than an LLM — the workflow only
needs a handful of clear-cut branches, and a rules engine is trivial to
unit test and to reason about in an incident review. (The real system's
spec allows an LLM here too; this scaled-down replica sticks to rules for
determinism in a demo, and to keep the interesting AWS-orchestration story
from getting diluted by a second, unrelated feature.)

Also writes the interim decision to DynamoDB — Step Functions holds the
authoritative in-flight state, but DynamoDB is the durable, queryable copy
other systems (a support dashboard, the Phase 3 reaper, Athena analytics)
would read without needing to touch a running execution.
"""

import os
import time

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
_dynamodb = boto3.resource("dynamodb")
_SESSIONS_TABLE = os.environ["SESSIONS_TABLE_NAME"]


def _decide(issue_type: str, diagnostics: dict, attempt: int) -> dict:
    error_codes = diagnostics.get("error_codes", [])
    packet_loss_pct = diagnostics.get("packet_loss_pct", 0)

    severe = "NO_SIGNAL" in error_codes or packet_loss_pct > 10

    if not severe:
        return {"recommended_action": "NONE", "network_impacting": False}

    if attempt == 1:
        return {"recommended_action": "REBOOT", "network_impacting": True}

    # Already rebooted once and it's still bad — escalate to a technician
    # rather than reboot again indefinitely.
    return {"recommended_action": "DISPATCH", "network_impacting": True}


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    state = dict(event)
    decision = _decide(state["issue_type"], state["diagnostics"], state["attempt"])
    state["decision"] = decision

    _dynamodb.Table(_SESSIONS_TABLE).update_item(
        Key={"case_id": state["case_id"]},
        UpdateExpression="SET attempt = :attempt, recommended_action = :action, updated_at = :now",
        ExpressionAttributeValues={
            ":attempt": state["attempt"],
            ":action": decision["recommended_action"],
            ":now": int(time.time()),
        },
    )

    logger.info("decision made", extra={"case_id": state["case_id"], "decision": decision})
    return state
