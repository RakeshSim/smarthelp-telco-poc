""""Trigger Diagnostics" step: gathers mock customer/device/network context.

No real customer/device/network systems exist for this POC — this is a
stand-in for what would otherwise be a call to a modem telemetry API. The
mock is seeded by (customer_id, attempt) so a given case's diagnostics are
reproducible across a demo, but different attempts of the same case (after
a reboot) show a different, evolving picture.
"""

import random

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()

_ISSUE_SEVERITY = {
    # issue_type -> (base_signal_dbm, base_packet_loss_pct, base_uptime_hours)
    "modem_offline": (None, 100.0, 0.0),
    "slow_speeds": (-75, 12.0, 240.0),
    "intermittent_drops": (-68, 6.0, 48.0),
}
_DEFAULT_SEVERITY = (-60, 2.0, 400.0)


def _gather_diagnostics(customer_id: str, issue_type: str, attempt: int) -> dict:
    rng = random.Random(f"{customer_id}:{attempt}")
    signal_dbm, packet_loss_pct, uptime_hours = _ISSUE_SEVERITY.get(issue_type, _DEFAULT_SEVERITY)

    # A prior reboot attempt (attempt > 1) plausibly improves things a bit,
    # even if it doesn't fully resolve the issue — makes the loop's second
    # pass look different from the first instead of repeating identically.
    if attempt > 1 and uptime_hours == 0.0:
        uptime_hours = rng.uniform(0.05, 0.5)
        packet_loss_pct = max(0.0, packet_loss_pct - rng.uniform(20, 40))

    error_codes = []
    if uptime_hours == 0.0:
        error_codes.append("NO_SIGNAL")
    elif packet_loss_pct > 10:
        error_codes.append("HIGH_PACKET_LOSS")

    return {
        "signal_strength_dbm": signal_dbm,
        "packet_loss_pct": round(packet_loss_pct + rng.uniform(-1.5, 1.5), 1),
        "uptime_hours": round(uptime_hours, 2),
        "error_codes": error_codes,
    }


@logger.inject_lambda_context(log_event=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    state = dict(event)
    diagnostics = _gather_diagnostics(state["customer_id"], state["issue_type"], state["attempt"])
    state["diagnostics"] = diagnostics
    logger.info("diagnostics gathered", extra={"case_id": state["case_id"], "diagnostics": diagnostics})
    return state
