import diagnose


def test_modem_offline_reports_no_signal_on_first_attempt(lambda_context):
    event = {"case_id": "case-1", "customer_id": "cust-123", "issue_type": "modem_offline", "attempt": 1}

    result = diagnose.lambda_handler(event, lambda_context)

    assert result["diagnostics"]["error_codes"] == ["NO_SIGNAL"]
    assert result["diagnostics"]["uptime_hours"] == 0.0


def test_modem_offline_improves_somewhat_after_a_reboot_attempt(lambda_context):
    event = {"case_id": "case-1", "customer_id": "cust-123", "issue_type": "modem_offline", "attempt": 2}

    result = diagnose.lambda_handler(event, lambda_context)

    assert result["diagnostics"]["uptime_hours"] > 0.0


def test_is_deterministic_for_the_same_customer_and_attempt(lambda_context):
    event = {"case_id": "case-1", "customer_id": "cust-999", "issue_type": "slow_speeds", "attempt": 1}

    first = diagnose.lambda_handler(dict(event), lambda_context)
    second = diagnose.lambda_handler(dict(event), lambda_context)

    assert first["diagnostics"] == second["diagnostics"]


def test_preserves_original_state_fields(lambda_context):
    event = {"case_id": "case-1", "customer_id": "cust-123", "issue_type": "modem_offline", "attempt": 1}

    result = diagnose.lambda_handler(event, lambda_context)

    assert result["case_id"] == "case-1"
    assert result["customer_id"] == "cust-123"
