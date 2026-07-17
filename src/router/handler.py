"""Access/router Lambda: the single entry point behind API Gateway.

Validates an inbound case and enqueues it to SQS — that's the entirety of
this Lambda's job. It does not touch DynamoDB or Step Functions directly;
the "starter" Lambda (triggered by the SQS event source mapping) owns
turning a queued message into a durable session + running workflow. That
split keeps this Lambda's response to the client fast and synchronous
regardless of how long session setup takes.
"""

import json
import os
import uuid
from datetime import UTC, datetime

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response, content_types
from aws_lambda_powertools.event_handler.exceptions import BadRequestError
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
app = APIGatewayHttpResolver()
_sqs = boto3.client("sqs")
_CASES_QUEUE_URL = os.environ.get("CASES_QUEUE_URL")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "telco-support-router"}


@app.post("/cases")
def create_case() -> Response:
    body = app.current_event.json_body or {}
    missing = [f for f in ("customer_id", "issue_type") if f not in body]
    if missing:
        raise BadRequestError(f"missing required field(s): {', '.join(missing)}")

    case_id = f"case-{uuid.uuid4().hex[:12]}"
    message = {
        "case_id": case_id,
        "customer_id": body["customer_id"],
        "issue_type": body["issue_type"],
        "submitted_at": datetime.now(UTC).isoformat(),
    }
    _sqs.send_message(QueueUrl=_CASES_QUEUE_URL, MessageBody=json.dumps(message))

    logger.info("case enqueued", extra={"case_id": case_id, **message})

    return Response(
        status_code=202,
        content_type=content_types.APPLICATION_JSON,
        body=json.dumps({"message": "case accepted", "case_id": case_id}),
    )


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)
