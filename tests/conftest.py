import os
import sys
from pathlib import Path

import pytest

# Every Lambda's source directory is added so its module (e.g. `diagnose`
# from src/diagnose/diagnose.py) can be imported directly by name. Each
# Lambda's entrypoint module has a unique basename (not a shared
# `handler.py`) specifically so this works without one import shadowing
# another in the same pytest session.
_SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
for _dir in sorted(_SRC_ROOT.iterdir()):
    if _dir.is_dir() and _dir.name != "layers":
        sys.path.insert(0, str(_dir))

# Several Lambda modules read required config from os.environ[...] at
# import time (fail fast if a real deployment is missing one). Tests need
# those names to exist *before* `import starter` / `import act` etc. runs
# at collection time — a pytest fixture would run too late. Values are
# fake ARNs/names; moto (or explicit mocking in each test) intercepts the
# actual AWS calls, so nothing here needs to resolve to a real resource.
# setdefault() so a test can still override one for a specific scenario.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("CASES_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123456789012/telco-support-test-cases")
os.environ.setdefault("SESSIONS_TABLE_NAME", "telco-support-test-sessions")
os.environ.setdefault("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:telco-support-test")
os.environ.setdefault("MAX_ATTEMPTS_PARAM_NAME", "/telco-support/test/config/max_diagnostic_attempts")
os.environ.setdefault("OPS_APPROVAL_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:telco-support-test-ops-approval")
os.environ.setdefault(
    "CUSTOMER_NOTIFICATIONS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:telco-support-test-customer-notifications"
)
os.environ.setdefault(
    "DISPATCH_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:telco-support-test-dispatch"
)


class _FakeLambdaContext:
    function_name = "telco-support-test-function"
    memory_limit_in_mb = 128
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:telco-support-test-function"
    aws_request_id = "test-request-id"


@pytest.fixture
def lambda_context() -> _FakeLambdaContext:
    # aws_lambda_powertools' Logger.inject_lambda_context reads real
    # attributes off the context object — every Lambda handler in this
    # repo uses that decorator, so every test invoking a handler needs a
    # context double, not `None`.
    return _FakeLambdaContext()
