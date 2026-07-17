import importlib
import json
import os

import boto3
import handler
from moto import mock_aws


def _apigw_event(method: str, path: str, body: dict | None = None) -> dict:
    # Shaped like a real API Gateway HTTP API (payload format 2.0) event,
    # routed through the $default stage/route as our Terraform config does.
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "test-api",
            "domainName": "test-api.execute-api.us-east-1.amazonaws.com",
            "http": {"method": method, "path": path, "protocol": "HTTP/1.1", "sourceIp": "127.0.0.1"},
            "requestId": "test-request-id",
            "routeKey": "$default",
            "stage": "$default",
            "time": "17/Jul/2026:00:00:00 +0000",
            "timeEpoch": 1784000000,
        },
        "isBase64Encoded": False,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def test_health_returns_ok(lambda_context):
    response = handler.lambda_handler(_apigw_event("GET", "/health"), lambda_context)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"status": "ok", "service": "telco-support-router"}


@mock_aws
def test_create_case_enqueues_and_returns_202(lambda_context):
    sqs = boto3.client("sqs", region_name="us-east-1")
    # Queue name must match the one baked into CASES_QUEUE_URL in
    # conftest.py, so moto's queue lookup and our env var agree.
    sqs.create_queue(QueueName="telco-support-test-cases")

    # handler.py creates its SQS client at module scope (the same pattern
    # the real Lambda uses, to reuse the client across warm invocations).
    # It was imported at collection time, before @mock_aws activated, so
    # reload it now — a well-known moto gotcha with module-level clients.
    importlib.reload(handler)

    body = {"customer_id": "cust-123", "issue_type": "modem_offline"}
    response = handler.lambda_handler(_apigw_event("POST", "/cases", body), lambda_context)

    assert response["statusCode"] == 202
    payload = json.loads(response["body"])
    assert payload["message"] == "case accepted"
    assert payload["case_id"].startswith("case-")

    messages = sqs.receive_message(QueueUrl=os.environ["CASES_QUEUE_URL"], MaxNumberOfMessages=1)["Messages"]
    enqueued = json.loads(messages[0]["Body"])
    assert enqueued == {
        "case_id": payload["case_id"],
        "customer_id": "cust-123",
        "issue_type": "modem_offline",
        "submitted_at": enqueued["submitted_at"],
    }


def test_create_case_rejects_missing_fields(lambda_context):
    response = handler.lambda_handler(_apigw_event("POST", "/cases", {"customer_id": "cust-123"}), lambda_context)

    assert response["statusCode"] == 400
    assert "issue_type" in json.loads(response["body"])["message"]
