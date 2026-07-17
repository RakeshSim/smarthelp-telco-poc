import json

import handler
import pytest


class _FakeLambdaContext:
    function_name = "telco-support-dev-router"
    memory_limit_in_mb = 128
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:telco-support-dev-router"
    aws_request_id = "test-request-id"


@pytest.fixture
def lambda_context():
    return _FakeLambdaContext()


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


def test_create_case_accepts_valid_body(lambda_context):
    body = {"customer_id": "cust-123", "issue_type": "modem_offline"}
    response = handler.lambda_handler(_apigw_event("POST", "/cases", body), lambda_context)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {
        "message": "case received",
        "customer_id": "cust-123",
        "issue_type": "modem_offline",
    }


def test_create_case_rejects_missing_fields(lambda_context):
    response = handler.lambda_handler(_apigw_event("POST", "/cases", {"customer_id": "cust-123"}), lambda_context)

    assert response["statusCode"] == 400
    assert "issue_type" in json.loads(response["body"])["message"]
