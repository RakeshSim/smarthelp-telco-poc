""""Take Action" step: carries out the recommended action.

REBOOT and DISPATCH are the two actions gated behind human approval before
this step ever runs (see the state machine's NeedsApproval choice) — this
Lambda doesn't re-check approval, it trusts the workflow already enforced
that. NONE is a no-op for cases where diagnostics didn't show a real
problem.

DISPATCH simulates calling an external field-dispatch/ticketing system
using an API key pulled from Secrets Manager. Cached at module scope after
the first fetch so a warm Lambda doesn't call GetSecretValue on every
invocation — unnecessary latency and API cost for a value that doesn't
change per-request.
"""

import json
import os
import random
import uuid

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
_secretsmanager = boto3.client("secretsmanager")
_DISPATCH_SECRET_ARN = os.environ["DISPATCH_SECRET_ARN"]

_dispatch_api_key_cache: str | None = None


def _get_dispatch_api_key() -> str:
    global _dispatch_api_key_cache
    if _dispatch_api_key_cache is None:
        secret = json.loads(_secretsmanager.get_secret_value(SecretId=_DISPATCH_SECRET_ARN)["SecretString"])
        _dispatch_api_key_cache = secret["api_key"]
    return _dispatch_api_key_cache


def _take_action(case_id: str, recommended_action: str, attempt: int) -> dict:
    rng = random.Random(f"{case_id}:{attempt}:act")

    if recommended_action == "REBOOT":
        # Mock: a remote reboot fixes the issue most, not all, of the time.
        return {"action_taken": "REBOOT", "success": rng.random() < 0.7}

    if recommended_action == "DISPATCH":
        _get_dispatch_api_key()  # simulates authenticating to the dispatch system
        return {"action_taken": "DISPATCH", "success": True, "ticket_id": f"TCK-{uuid.uuid4().hex[:8].upper()}"}

    return {"action_taken": "NONE", "success": True}


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    state = dict(event)
    result = _take_action(state["case_id"], state["decision"]["recommended_action"], state["attempt"])
    state["action_result"] = result
    logger.info("action taken", extra={"case_id": state["case_id"], "action_result": result})
    return state
