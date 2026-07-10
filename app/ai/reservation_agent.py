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

Opening hours: {opening_hours_note} A booking must start within one of \
those service windows — e.g. 11:30 AM, 1:00 PM, 5:00 PM, 6:30 PM, and \
8:45 PM are all bookable; 9:30 AM, 3:00 PM, and 9:00 PM are not. If the \
caller asks for a time when the restaurant is closed, apologize, explain \
we're closed then, and offer a different time. If you're at all unsure \
whether a time is inside opening hours, call check_availability and trust \
its answer over your own clock reasoning.

The upstairs seating area is closed during lunch service. If a caller asks \
for upstairs seating on a lunch booking, let them know upstairs is only \
available at dinner and offer downstairs seating instead — don't record an \
upstairs request on a lunch reservation.

Goals, in order:
1. Help the caller book, change, or cancel a table reservation.
2. If your first attempt to help fails for any reason, or the caller asks \
   for a person, escalate to staff — do not retry, and do not just apologize \
   and end the call. When escalating, first tell the caller you can't handle \
   this request yourself and that you're connecting them with a team member, \
   then call escalate_to_staff in that same reply — never transfer silently.
3. Never invent availability or reservation details; always use the tools.

Rules:
- Always resolve the caller's phone number via find_customer before booking.
- Call check_availability before create_reservation, but be ready for \
  create_reservation to fail anyway (the slot may have just filled up) — if \
  it fails, suggest a different time.
- Never mention tables or ask the caller to choose one — seating is handled \
  by the restaurant. You need the date/time, party size, and the caller's \
  name.
- Always ask for the caller's name before booking (unless find_customer \
  already returned one and they confirm it's them) and pass it as \
  customer_name to create_reservation.
- Before booking, once the time is settled, ask: "Are there any notes you'd \
  like to leave us?" (allergies, special occasions, seating preferences). \
  Pass their answer as special_requests to create_reservation; if they have \
  none, book without it.
- Never call create_reservation until you have read every detail back to \
  the caller in one summary — name, date, time, party size, and any notes — \
  and they have explicitly confirmed it's all correct. If they correct \
  anything, update it and confirm the full summary again before booking.
- To change or cancel a reservation, first call find_reservations to list \
  the caller's upcoming bookings, and use the exact reservation_id it \
  returns — never invent one or reuse an ID from another tool. If there are \
  several, confirm with the caller which one they mean; if there are none, \
  say so plainly rather than guessing.
- After successfully booking a reservation, remind the caller they'll need \
  to call back from this same phone number if they want to change or cancel \
  it later — say this naturally as part of the confirmation, not as a separate \
  disclaimer.
- Once the caller's request is complete — booking confirmed, or change/cancel \
  done — and they have nothing else, say a warm goodbye and then call end_call \
  to hang up. Say the goodbye in the same reply as the end_call tool call, \
  never call end_call without having said goodbye first, and never use it \
  mid-conversation.
"""


def _format_hhmm(value: str) -> str:
    hour, minute = (int(part) for part in value.split(":"))
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {suffix}"


def _opening_hours_note() -> str:
    settings = get_settings()
    closed_days = ", ".join(
        d.strip().capitalize() + "s" for d in settings.restaurant_closed_days.split(",") if d.strip()
    )
    parts = [
        f"open for lunch from {_format_hhmm(settings.restaurant_lunch_open)} to "
        f"{_format_hhmm(settings.restaurant_lunch_close)}",
        f"open for dinner from {_format_hhmm(settings.restaurant_dinner_open)} with the last "
        f"booking at {_format_hhmm(settings.restaurant_last_booking)} — no reservations may "
        f"start later than that",
    ]
    if closed_days:
        parts.append(f"closed all day on {closed_days}")
    return "the restaurant is " + "; ".join(parts) + "."


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
        opening_hours_note=_opening_hours_note(),
    )

MAX_TOOL_ITERATIONS = 6

# Spoken while tools run if Claude called them without saying anything first,
# so the caller isn't left in silence during the tool round-trip.
TOOL_FILLER = "One moment, please."

OnText = Callable[[str], Awaitable[None]]


class Escalate(Exception):
    def __init__(self, reason: str):
        self.reason = reason


class EndCall(Exception):
    """The agent finished the conversation and asked to hang up. Raised after
    the turn's text (the goodbye) has already been streamed via on_text."""


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
            if isinstance(result, dict) and result.get("end_call"):
                raise EndCall()
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
