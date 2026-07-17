""""Interpret Results" step: decides whether the case is resolved, needs
another diagnose/act loop, or should be escalated.

Keeps the loop bounded without relying solely on Step Functions machinery:
a REBOOT that doesn't work loops back to TriggerDiagnostics (incrementing
`attempt`), but only up to `max_attempts` — after that, or once a
technician DISPATCH has happened, the case always resolves one way and the
workflow can't spin forever regardless of how `max_attempts` is configured.
"""

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()


def _decide_outcome(recommended_action: str, action_result: dict, attempt: int, max_attempts: int) -> dict:
    if recommended_action == "NONE":
        return {"resolved": True, "resolution_type": "RESOLVED"}

    if recommended_action == "DISPATCH":
        # A technician is now handling it physically — that's the terminal
        # outcome for this workflow regardless of `success`.
        return {"resolved": True, "resolution_type": "ESCALATED"}

    if recommended_action == "REBOOT":
        if action_result.get("success"):
            return {"resolved": True, "resolution_type": "RESOLVED"}
        if attempt < max_attempts:
            return {"resolved": False, "resolution_type": None}
        return {"resolved": True, "resolution_type": "ESCALATED"}

    raise ValueError(f"unrecognized recommended_action: {recommended_action!r}")


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    state = dict(event)
    outcome = _decide_outcome(
        state["decision"]["recommended_action"],
        state["action_result"],
        state["attempt"],
        state["max_attempts"],
    )
    state["outcome"] = outcome

    if not outcome["resolved"]:
        state["attempt"] += 1

    logger.info(
        "outcome decided", extra={"case_id": state["case_id"], "outcome": outcome, "next_attempt": state["attempt"]}
    )
    return state
