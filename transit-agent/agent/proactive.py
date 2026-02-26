"""Proactive trigger system: evaluate ride context every 30s and inject offers at most once per ride."""

import asyncio
import logging
from typing import Callable, Awaitable

from agent.context import RideContext

logger = logging.getLogger(__name__)

INTERVAL_SEC = 30

TRIGGERS = [
    ("boarding", lambda ctx: ctx.elapsed_seconds < 15, "Welcome + one capability offer"),
    ("long_ride", lambda ctx: ctx.ride_duration_seconds > 600 and ctx.elapsed_seconds < 120, "Offer ambient lighting or music"),
    ("pre_arrival", lambda ctx: ctx.eta_seconds < 180, "Heads up, stop name"),
    ("nighttime", lambda ctx: ctx.hour_of_day > 20 or ctx.hour_of_day < 6, "Offer to adjust cabin lighting"),
    ("mid_ride_silence", lambda ctx: ctx.elapsed_seconds > 300, "Single gentle offer (no recent interaction)"),
]

# Default messages for each trigger (agent will respond in its tone)
TRIGGER_MESSAGES = {
    "boarding": "[PROACTIVE] A passenger just boarded. Give a brief welcome and one short capability offer (e.g. lights, climate, or music).",
    "long_ride": "[PROACTIVE] This is a long ride and we're early in it. Offer ambient lighting or music once, briefly.",
    "pre_arrival": "[PROACTIVE] We're arriving soon. Give a heads up with the next stop name and approximate time.",
    "nighttime": "[PROACTIVE] It's nighttime. Offer to adjust cabin lighting if they'd like.",
    "mid_ride_silence": "[PROACTIVE] Mid-ride with no recent interaction. Make one gentle, brief offer (e.g. comfort or info). Do not repeat previous offers.",
}


async def proactive_loop(
    get_context: Callable[[], RideContext],
    on_trigger: Callable[[str, str], Awaitable[None]],
    offered: set[str],
    interval_sec: float = INTERVAL_SEC,
) -> None:
    """
    Every interval_sec, evaluate triggers. If one fires and hasn't been offered this session,
    call on_trigger(trigger_key, user_message) and add key to offered.
    """
    while True:
        await asyncio.sleep(interval_sec)
        ctx = get_context()
        for key, condition, _ in TRIGGERS:
            if key in offered:
                continue
            if not condition(ctx):
                continue
            offered.add(key)
            message = TRIGGER_MESSAGES.get(key, f"[PROACTIVE] Trigger: {key}")
            try:
                await on_trigger(key, message)
            except Exception as e:
                logger.exception("Proactive trigger %s failed: %s", key, e)
