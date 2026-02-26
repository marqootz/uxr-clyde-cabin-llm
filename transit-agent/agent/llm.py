"""Claude agent with vehicle control tools and ride context injection."""

import json
import logging
from typing import Any

import anthropic
import httpx

from agent.context import RideContext
from agent import display_server
import config

logger = logging.getLogger(__name__)

VEHICLE_BASE = f"http://127.0.0.1:{config.VEHICLE_API_PORT}"

TOOLS = [
    {
        "name": "set_lights",
        "description": "Set cabin lighting brightness (0-100) and color temperature (warm, neutral, cool).",
        "input_schema": {
            "type": "object",
            "properties": {
                "brightness": {"type": "integer", "description": "0-100"},
                "color_temp": {"type": "string", "description": "warm | neutral | cool"},
            },
            "required": ["brightness", "color_temp"],
        },
    },
    {
        "name": "set_climate",
        "description": "Set cabin temperature (F) and fan speed (off, low, medium, high, auto).",
        "input_schema": {
            "type": "object",
            "properties": {
                "temp_f": {"type": "integer", "description": "Temperature in Fahrenheit"},
                "fan_speed": {"type": "string", "description": "off | low | medium | high | auto"},
            },
            "required": ["temp_f", "fan_speed"],
        },
    },
    {
        "name": "set_audio",
        "description": "Control cabin audio: action (e.g. play, pause, stop), optional genre for play.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "e.g. play, pause, stop"},
                "genre": {"type": "string", "description": "Optional genre when playing", "default": None},
            },
            "required": ["action"],
        },
    },
    {
        "name": "get_ride_info",
        "description": "Get current ride context (route, stops, ETA, cabin state). No parameters.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_display",
        "description": "Update the cabin display. layout: idle | speaking | status | arrival. data: dict of layout-specific fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layout": {"type": "string", "description": "idle | speaking | status | arrival"},
                "data": {"type": "object", "description": "Layout-specific key-value pairs"},
            },
            "required": ["layout", "data"],
        },
    },
]

SYSTEM_PROMPT_TEMPLATE = """You are the in-cabin voice assistant for a small autonomous public transit vehicle. You are calm, brief, and co-pilot in tone. Keep responses to 2 sentences max unless the user asks for more. Do not ask follow-up questions unless strictly necessary. When you take an action (lights, climate, audio), confirm briefly in speech and use send_display to push a status card.

Current ride context (JSON):
{context_json}

Proactive offers already made this ride (do not repeat these): {offers_made}

When taking an action, always call send_display with layout "status" and a short title/detail so the passenger sees confirmation on the display."""


async def _call_vehicle(path: str, method: str = "GET", body: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        if method == "GET":
            r = await client.get(VEHICLE_BASE + path)
        else:
            r = await client.post(VEHICLE_BASE + path, json=body or {})
        r.raise_for_status()
        return r.json()


async def execute_tool(name: str, arguments: dict[str, Any], ctx: RideContext) -> str:
    """Execute one tool and return a string result for Claude."""
    try:
        if name == "set_lights":
            out = await _call_vehicle("/lights", "POST", arguments)
            return json.dumps(out)
        if name == "set_climate":
            out = await _call_vehicle("/climate", "POST", arguments)
            return json.dumps(out)
        if name == "set_audio":
            out = await _call_vehicle("/audio", "POST", arguments)
            return json.dumps(out)
        if name == "get_ride_info":
            return json.dumps({
                "route_name": ctx.route_name,
                "current_stop": ctx.current_stop,
                "next_stop": ctx.next_stop,
                "eta_seconds": ctx.eta_seconds,
                "ride_duration_seconds": ctx.ride_duration_seconds,
                "elapsed_seconds": ctx.elapsed_seconds,
                "hour_of_day": ctx.hour_of_day,
                "passenger_count": ctx.passenger_count,
                "cabin": ctx.cabin.to_dict(),
            })
        if name == "send_display":
            layout = arguments.get("layout", "idle")
            data = arguments.get("data") or {}
            await display_server.send_layout(layout, data)
            return json.dumps({"ok": True, "layout": layout})
        return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        logger.exception("Tool %s failed: %s", name, e)
        return json.dumps({"error": str(e)})


def _build_system_prompt(ctx: RideContext, offers_made: list[str]) -> str:
    import json as _json
    context_dict = {
        "route_name": ctx.route_name,
        "current_stop": ctx.current_stop,
        "next_stop": ctx.next_stop,
        "eta_seconds": ctx.eta_seconds,
        "ride_duration_seconds": ctx.ride_duration_seconds,
        "elapsed_seconds": ctx.elapsed_seconds,
        "hour_of_day": ctx.hour_of_day,
        "passenger_count": ctx.passenger_count,
        "cabin": ctx.cabin.to_dict(),
    }
    context_json = _json.dumps(context_dict, indent=2)
    return SYSTEM_PROMPT_TEMPLATE.format(
        context_json=context_json,
        offers_made=", ".join(offers_made) or "none",
    )


async def run_turn(
    user_message: str,
    ctx: RideContext,
    offers_made: list[str],
    conversation: list[dict],
) -> tuple[str, list[dict]]:
    """
    Send user message to Claude with context and tools; execute tool calls and loop until done.
    Returns (final assistant text for TTS, updated conversation messages).
    """
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    system = _build_system_prompt(ctx, offers_made)
    messages = conversation + [{"role": "user", "content": user_message}]
    final_text = ""

    while True:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system,
            messages=messages,
            tools=TOOLS,
            tool_choice={"type": "auto"},
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    final_text += block.text
            messages = messages + [
                {"role": "assistant", "content": response.content},
            ]
            break

        if response.stop_reason == "tool_use":
            messages = messages + [{"role": "assistant", "content": response.content}]
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    tool_id = block.id
                    name = block.name
                    args = block.input if isinstance(block.input, dict) else json.loads(block.input or "{}")
                    result = await execute_tool(name, args, ctx)
                    messages.append({
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": result}],
                    })
            continue

        # Fallback
        for block in response.content:
            if hasattr(block, "text") and block.text:
                final_text += block.text
        messages = messages + [{"role": "assistant", "content": response.content}]
        break

    return (final_text.strip(), messages)


def add_proactive_offer(offers_made: list[str], offer_key: str) -> None:
    """Record that we made this proactive offer so it is not repeated."""
    if offer_key and offer_key not in offers_made:
        offers_made.append(offer_key)
