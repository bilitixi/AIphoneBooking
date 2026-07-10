import inspect
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import claude_client, tools
from app.core.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """\
You are the phone reservation agent for ABC Restaurant. You are speaking to \
a caller over the phone, so keep replies short, natural, and conversational \
— this is voice, not chat.

Right now it is {current_datetime} ({timezone}). For reference, the next \
two weeks are:
{calendar}
When the caller says a relative date ("Friday", "tomorrow", "next week"), \
look it up in the calendar above — do not compute weekdays yourself. Pass \
starts_at to tools as an ISO-8601 datetime including the UTC offset for \
{timezone}.

The caller is calling from {caller_phone_number} — this is already known \
from caller ID, so never ask for their phone number. Reservations are \
automatically tied to this number regardless of what you pass to the tools. \
When calling find_customer or create_reservation, use this number directly.

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


def _build_system_prompt(caller_phone_number: str) -> str:
    tz_name = get_settings().restaurant_timezone
    now = datetime.now(ZoneInfo(tz_name))
    calendar = "\n".join(
        f"- {day.strftime('%A')} {day.strftime('%Y-%m-%d')}" + (" (today)" if offset == 0 else "")
        for offset in range(14)
        for day in [now + timedelta(days=offset)]
    )
    return SYSTEM_PROMPT_TEMPLATE.format(
        current_datetime=now.strftime("%A, %B %d, %Y, %I:%M %p"),
        timezone=tz_name,
        caller_phone_number=caller_phone_number,
        calendar=calendar,
    )

MAX_TOOL_ITERATIONS = 6

# Spoken while tools run if Claude called them without saying anything first,
# so the caller isn't left in silence during the tool round-trip.
TOOL_FILLER = "One moment, please."

OnText = Callable[[str], Awaitable[None]]


class Escalate(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def _split_complete_sentences(buf: str) -> tuple[str, str]:
    """Splits off text up to the last sentence boundary (., !, ? followed by
    whitespace), returning (complete, remainder). Requiring trailing
    whitespace keeps things like "6.30" intact."""
    end = -1
    for m in re.finditer(r"[.!?](?=\s)", buf):
        end = m.end()
    if end == -1:
        return "", buf
    return buf[:end], buf[end:]


async def run_turn(
    db: AsyncSession,
    caller_phone_number: str,
    conversation: list[dict],
    on_text: OnText | None = None,
) -> tuple[str, list[dict]]:
    """Runs one caller turn through Claude, executing any tool calls, and
    returns (final_text_reply, updated_conversation). Raises Escalate if the
    agent invokes escalate_to_staff.

    All caller-audible text is delivered through on_text as soon as each
    sentence is complete — including text emitted before tool calls — so
    speech synthesis can start while Claude is still generating. The returned
    full text is for logging; callers using on_text must not speak it again."""
    system_prompt = _build_system_prompt(caller_phone_number)
    spoke_anything = False

    for _ in range(MAX_TOOL_ITERATIONS):
        assistant_blocks: list[dict] = []
        text_reply = ""
        tool_uses = []
        sentence_buf = ""

        async for event in claude_client.stream_reply(system_prompt, conversation, tools.TOOL_DEFINITIONS):
            if (
                on_text
                and event.type == "content_block_delta"
                and getattr(event.delta, "type", None) == "text_delta"
            ):
                sentence_buf += event.delta.text
                complete, sentence_buf = _split_complete_sentences(sentence_buf)
                if complete.strip():
                    spoke_anything = True
                    await on_text(complete.strip())
            elif event.type == "content_block_stop" and getattr(event, "content_block", None):
                block = event.content_block
                if block.type == "text":
                    text_reply += block.text
                    assistant_blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    assistant_blocks.append(
                        {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                    )

        if on_text and sentence_buf.strip():
            spoke_anything = True
            await on_text(sentence_buf.strip())

        conversation.append({"role": "assistant", "content": assistant_blocks})

        if not tool_uses:
            return text_reply, conversation

        if on_text and not spoke_anything:
            await on_text(TOOL_FILLER)
            spoke_anything = True

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
    fallback = "I'm having trouble completing that — let me connect you with someone who can help."
    if on_text:
        await on_text(fallback)
    return fallback, conversation


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
