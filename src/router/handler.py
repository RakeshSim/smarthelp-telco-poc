"""Access/router Lambda: the single entry point behind API Gateway.

Phase 1 scope: accept and validate an inbound case, acknowledge it.
Phase 2 will replace the "acknowledge" step with an SQS send that kicks
off the Step Functions diagnose/act/resolve workflow.
"""

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.event_handler.exceptions import BadRequestError
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
app = APIGatewayHttpResolver()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "telco-support-router"}


@app.post("/cases")
def create_case() -> dict:
    body = app.current_event.json_body or {}
    missing = [f for f in ("customer_id", "issue_type") if f not in body]
    if missing:
        raise BadRequestError(f"missing required field(s): {', '.join(missing)}")

    logger.info("case received", extra={"customer_id": body["customer_id"], "issue_type": body["issue_type"]})

    # Phase 1 placeholder: real hand-off to the workflow lands in Phase 2.
    return {
        "message": "case received",
        "customer_id": body["customer_id"],
        "issue_type": body["issue_type"],
    }


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)
