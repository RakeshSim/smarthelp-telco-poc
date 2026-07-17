import interpret_results


def _event(recommended_action: str, action_result: dict, attempt: int, max_attempts: int = 2) -> dict:
    return {
        "case_id": "case-1",
        "issue_type": "modem_offline",
        "attempt": attempt,
        "max_attempts": max_attempts,
        "decision": {"recommended_action": recommended_action, "network_impacting": recommended_action != "NONE"},
        "action_result": action_result,
    }


def test_no_action_needed_is_immediately_resolved(lambda_context):
    result = interpret_results.lambda_handler(
        _event("NONE", {"action_taken": "NONE", "success": True}, attempt=1), lambda_context
    )

    assert result["outcome"] == {"resolved": True, "resolution_type": "RESOLVED"}
    assert result["attempt"] == 1


def test_successful_reboot_resolves(lambda_context):
    event = _event("REBOOT", {"action_taken": "REBOOT", "success": True}, attempt=1)

    result = interpret_results.lambda_handler(event, lambda_context)

    assert result["outcome"] == {"resolved": True, "resolution_type": "RESOLVED"}


def test_failed_reboot_with_attempts_remaining_loops(lambda_context):
    event = _event("REBOOT", {"action_taken": "REBOOT", "success": False}, attempt=1, max_attempts=2)

    result = interpret_results.lambda_handler(event, lambda_context)

    assert result["outcome"] == {"resolved": False, "resolution_type": None}
    assert result["attempt"] == 2  # incremented so the loop's next diagnose pass knows this is attempt 2


def test_failed_reboot_out_of_attempts_escalates(lambda_context):
    event = _event("REBOOT", {"action_taken": "REBOOT", "success": False}, attempt=2, max_attempts=2)

    result = interpret_results.lambda_handler(event, lambda_context)

    assert result["outcome"] == {"resolved": True, "resolution_type": "ESCALATED"}
    assert result["attempt"] == 2  # not incremented — the loop is over, not continuing


def test_dispatch_always_escalates_regardless_of_success(lambda_context):
    event = _event("DISPATCH", {"action_taken": "DISPATCH", "success": True, "ticket_id": "TCK-1"}, attempt=2)

    result = interpret_results.lambda_handler(event, lambda_context)

    assert result["outcome"] == {"resolved": True, "resolution_type": "ESCALATED"}
