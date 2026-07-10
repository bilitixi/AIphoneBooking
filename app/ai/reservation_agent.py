import inspect
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import claude_client, tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the phone reservation agent for ABC Restaurant. You are speaking to \
a caller over the phone, so keep replies short, natural, and conversational \
— this is voice, not chat.

Goals, in order:
1. Help the caller book, change, or cancel a table reservation.
2. If your first attempt to help fails for any reason, or the caller asks \
   for a person, call escalate_to_staff immediately — do not retry, and do \
   not just apologize and end the call.
3. Never invent availability or reservation details; always use the tools.

Rules:
- Always resolve the caller's phone number via find_customer before booking.
- Call check_tables before create_reservation, but be ready for \
  create_reservation to fail anyway (someone else may have just booked the \
  same table) — if it fails, offer the alternatives it returns.
- modify_reservation and cancel_reservation only work for reservations tied \
  to the caller's own phone number. If a lookup fails, say so plainly rather \
  than guessing at another reservation.
- After successfully booking a reservation, remind the caller they'll need \
  to call back from this same phone number if they want to change or cancel \
  it later — say this naturally as part of the confirmation, not as a separate \
  disclaimer.
"""

MAX_TOOL_ITERATIONS = 6


class Escalate(Exception):
    def __init__(self, reason: str):
        self.reason = reason


async def run_turn(
    db: AsyncSession, caller_phone_number: str, conversation: list[dict]
) -> tuple[str, list[dict]]:
    """Runs one caller turn through Claude, executing any tool calls, and
    returns (final_text_reply, updated_conversation). Raises Escalate if the
    agent invokes escalate_to_staff."""
    for _ in range(MAX_TOOL_ITERATIONS):
        assistant_blocks: list[dict] = []
        text_reply = ""
        tool_uses = []

        async for event in claude_client.stream_reply(SYSTEM_PROMPT, conversation, tools.TOOL_DEFINITIONS):
            if event.type == "content_block_stop" and getattr(event, "content_block", None):
                block = event.content_block
                if block.type == "text":
                    text_reply += block.text
                    assistant_blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    assistant_blocks.append(
                        {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                    )

        conversation.append({"role": "assistant", "content": assistant_blocks})

        if not tool_uses:
            return text_reply, conversation

        tool_results = []
        for tool_use in tool_uses:
            result = await _execute_tool(db, caller_phone_number, tool_use.name, tool_use.input)
            if isinstance(result, dict) and result.get("escalate"):
                raise Escalate(result.get("reason", "caller requested a person"))
            tool_results.append(
                {"type": "tool_result", "tool_use_id": tool_use.id, "content": _serialize(result)}
            )

        conversation.append({"role": "user", "content": tool_results})

    logger.warning("Hit MAX_TOOL_ITERATIONS without a final reply for %s", caller_phone_number)
    return (
        "I'm having trouble completing that — let me connect you with someone who can help.",
        conversation,
    )


async def _execute_tool(db: AsyncSession, caller_phone_number: str, name: str, tool_input: dict) -> dict:
    fn = tools.DISPATCH.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}

    kwargs = dict(tool_input)
    params = inspect.signature(fn).parameters
    if "db" in params:
        kwargs["db"] = db
    # The agent should never be able to act as a different caller than the
    # one on the line, regardless of what phone_number it passes as input.
    if "phone_number" in params:
        kwargs["phone_number"] = caller_phone_number

    try:
        return await fn(**kwargs)
    except Exception:
        logger.exception("Tool %s failed", name)
        return {"error": f"{name} failed unexpectedly"}


def _serialize(result: dict) -> str:
    import json

    return json.dumps(result)
