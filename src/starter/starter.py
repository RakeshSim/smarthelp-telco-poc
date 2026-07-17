"""SQS consumer: turns an enqueued case into a durable session record and
starts the Step Functions workflow for it.

Split out from the router Lambda so the router stays a fast, synchronous
"validate and enqueue" call — this Lambda does the (slightly slower)
DynamoDB write + StartExecution call, decoupled from the client's request.
"""

import json
import os
import time

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError

logger = Logger()

_dynamodb = boto3.resource("dynamodb")
_sfn = boto3.client("stepfunctions")
_ssm = boto3.client("ssm")

_SESSIONS_TABLE = os.environ["SESSIONS_TABLE_NAME"]
_STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]
_MAX_ATTEMPTS_PARAM = os.environ["MAX_ATTEMPTS_PARAM_NAME"]

# Session records outlive their workflow so they're queryable afterward,
# but not forever — DynamoDB TTL sweeps them up automatically.
_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60

# Fetched once per cold start, not per invocation — avoids an SSM API call
# (and its latency/throttling risk) on every single case.
_max_attempts_cache: int | None = None


def _get_max_attempts() -> int:
    global _max_attempts_cache
    if _max_attempts_cache is None:
        value = _ssm.get_parameter(Name=_MAX_ATTEMPTS_PARAM)["Parameter"]["Value"]
        _max_attempts_cache = int(value)
        logger.info("loaded config from SSM", extra={"max_diagnostic_attempts": _max_attempts_cache})
    return _max_attempts_cache


def _start_case(case: dict) -> None:
    # Order matters for idempotency under SQS's at-least-once delivery:
    # both StartExecution and the DynamoDB write are individually
    # idempotent (same execution `name`; a ConditionExpression), but doing
    # them in *this* order means a crash between the two is always safely
    # retryable on redelivery — StartExecution again is a no-op
    # (ExecutionAlreadyExists), and the DynamoDB write still hasn't
    # happened yet, so it proceeds normally. Doing the DynamoDB write
    # first would leave a case permanently "started" with no execution if
    # the Lambda died right after it.
    case_id = case["case_id"]

    workflow_input = {
        "case_id": case_id,
        "customer_id": case["customer_id"],
        "issue_type": case["issue_type"],
        "attempt": 1,
        "max_attempts": _get_max_attempts(),
    }

    try:
        _sfn.start_execution(
            stateMachineArn=_STATE_MACHINE_ARN,
            name=case_id,
            input=json.dumps(workflow_input),
        )
        logger.info("started workflow", extra={"case_id": case_id})
    except _sfn.exceptions.ExecutionAlreadyExists:
        logger.info("execution already exists, continuing (duplicate delivery)", extra={"case_id": case_id})

    table = _dynamodb.Table(_SESSIONS_TABLE)
    try:
        table.put_item(
            Item={
                "case_id": case_id,
                "customer_id": case["customer_id"],
                "issue_type": case["issue_type"],
                "status": "IN_PROGRESS",
                "attempt": 1,
                "created_at": case["submitted_at"],
                "updated_at": case["submitted_at"],
                "ttl": int(time.time()) + _SESSION_TTL_SECONDS,
            },
            ConditionExpression="attribute_not_exists(case_id)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info("session record already exists, skipping (duplicate delivery)", extra={"case_id": case_id})
            return
        raise


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    for record in event["Records"]:
        _start_case(json.loads(record["body"]))
    return {"processed": len(event["Records"])}
