import asyncio
import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from twilio.rest import Client as TwilioClient

from app.ai.reservation_agent import TOOL_FILLER, EndCall, Escalate, run_turn
from app.core.config import get_settings
from app.db.models import PhoneCall
from app.db.session import async_session_factory
from app.voice.synthesizer import create_synthesizer
from app.voice.transcriber import create_transcriber

logger = logging.getLogger(__name__)
router = APIRouter()


GREETING = (
    "Hi, thanks for calling ABC Restaurant! I'm your reservation assistant — "
    "are you looking to book a table, or change or cancel an existing reservation?"
)

# Static phrases spoken on every call: synthesized once, then replayed from
# memory so the caller doesn't wait on a TTS round-trip for canned audio.
_CACHEABLE_PHRASES = {GREETING, TOOL_FILLER}
_audio_cache: dict[str, list[bytes]] = {}

# How long after the agent stops speaking to keep ignoring transcripts. Phone
# lines (speakerphone, VOIP echo) can leak the agent's own TTS audio back
# into the caller's mic; without this, STT transcribes that leakage as caller
# speech and the agent ends up replying to itself.
ECHO_GRACE_SECONDS = 0.4


async def _send_audio(websocket: WebSocket, stream_sid: str, audio_chunk: bytes) -> None:
    await websocket.send_text(
        json.dumps(
            {
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": base64.b64encode(audio_chunk).decode()},
            }
        )
    )


async def _speak(websocket: WebSocket, synthesizer, stream_sid: str, text: str) -> None:
    cached = _audio_cache.get(text)
    if cached is not None:
        for audio_chunk in cached:
            await _send_audio(websocket, stream_sid, audio_chunk)
        return

    chunks: list[bytes] = []
    async for audio_chunk in synthesizer.stream(text):
        chunks.append(audio_chunk)
        await _send_audio(websocket, stream_sid, audio_chunk)
    if text in _CACHEABLE_PHRASES and chunks:
        _audio_cache[text] = chunks


async def _escalate_call(call_sid: str) -> None:
    """Redirects the live call to the staff line — same <Dial> path used for
    takeaway transfers. Done via the REST API since we can't return TwiML
    over an already-connected media stream."""
    settings = get_settings()
    client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    twiml = f'<Response><Say>Connecting you to a team member.</Say><Dial>{settings.twilio_staff_number}</Dial></Response>'
    client.calls(call_sid).update(twiml=twiml)


async def _hangup_call(call_sid: str) -> None:
    settings = get_settings()
    client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    client.calls(call_sid).update(status="completed")


@router.websocket("/ws/reservation")
async def reservation_media_stream(websocket: WebSocket) -> None:
    await websocket.accept()

    # Twilio Media Streams always sends a "start" event first, which carries
    # the real CallSid — the query string on the <Stream url="..."> is not
    # reliably forwarded by Twilio, so we can't trust query_params for this.
    call_sid: str | None = None
    stream_sid: str | None = None
    while call_sid is None:
        raw = await websocket.receive_text()
        message = json.loads(raw)
        if message.get("event") == "start":
            call_sid = message["start"]["callSid"]
            stream_sid = message["start"]["streamSid"]
        elif message.get("event") == "stop":
            await websocket.close(code=1008)
            return

    transcriber = create_transcriber()
    synthesizer = create_synthesizer()
    conversation: list[dict] = []
    # Lives for the whole call; confirm_phone_number uses it to cap retries
    # instead of trusting the model to count its own confirmation attempts.
    call_state: dict = {}

    # Guards handle_transcripts against hearing the agent's own voice echoed
    # back through the caller's line. `speaking` covers the audio actually in
    # flight; mute_until covers the tail-off grace period after it finishes.
    speaking = False
    mute_until = 0.0

    async def speak(text: str) -> None:
        nonlocal speaking, mute_until
        speaking = True
        try:
            await _speak(websocket, synthesizer, stream_sid, text)
        finally:
            speaking = False
            mute_until = asyncio.get_running_loop().time() + ECHO_GRACE_SECONDS

    async with async_session_factory() as db:
        result = await db.execute(select(PhoneCall).where(PhoneCall.call_sid == call_sid))
        call = result.scalar_one_or_none()
        if call is None:
            await websocket.close(code=1008)
            return

        caller_phone_number = call.from_number

        # Not seeded into `conversation`: the Anthropic Messages API requires
        # the first message to have role "user", so an assistant-authored
        # greeting can't lead the history — it's spoken and logged only.
        logger.info("agent [%s]: %s", call_sid, GREETING)
        await speak(GREETING)

        # Resolved by the main receive loop when Twilio reports our mark has
        # played — i.e. the caller has actually heard everything sent so far.
        playback_done: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

        async def speak_text(text: str) -> None:
            await speak(text)

        async def wait_until_played() -> None:
            """Blocks until all audio queued so far has played to the caller,
            so hangups/transfers never cut the agent off mid-sentence."""
            await websocket.send_text(
                json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": "flush"}})
            )
            try:
                await asyncio.wait_for(asyncio.shield(playback_done), timeout=20)
            except asyncio.TimeoutError:
                logger.warning("Never got playback mark for %s; proceeding anyway", call_sid)

        response_delay_seconds = get_settings().agent_response_delay_ms / 1000

        async def handle_transcripts():
            nonlocal conversation
            async for transcript in transcriber.finalized_transcripts():
                if speaking or asyncio.get_running_loop().time() < mute_until:
                    logger.info(
                        "caller [%s]: dropped transcript while agent was speaking (echo guard): %s",
                        call_sid,
                        transcript,
                    )
                    continue

                logger.info("caller [%s]: %s", call_sid, transcript)
                conversation.append({"role": "user", "content": transcript})

                # Deliberate pause so the agent doesn't reply the instant the
                # caller stops talking — makes the turn-taking feel natural
                # instead of rushed, independent of how fast Claude/TTS are.
                await asyncio.sleep(response_delay_seconds)

                try:
                    # run_turn speaks each sentence via speak_text as soon as
                    # it's generated; the returned reply is logged, not spoken.
                    reply, conversation = await run_turn(
                        db, caller_phone_number, conversation, call_state, on_text=speak_text
                    )
                except Escalate as esc:
                    # The agent's own handoff explanation was already streamed
                    # via speak_text; let it finish playing before Twilio
                    # replaces the call with the <Dial> transfer.
                    logger.info("agent [%s]: escalating: %s", call_sid, esc.reason)
                    call.outcome = "escalated_to_staff"
                    await db.commit()
                    await wait_until_played()
                    await _escalate_call(call_sid)
                    return
                except EndCall:
                    # The goodbye was already streamed via speak_text; don't
                    # hang up until the caller has heard it.
                    logger.info("agent [%s]: call ended by agent", call_sid)
                    call.outcome = call.outcome or "handled_by_ai"
                    await db.commit()
                    await wait_until_played()
                    await _hangup_call(call_sid)
                    return
                except Exception:
                    logger.exception("Unhandled error running turn for %s", caller_phone_number)
                    call.outcome = "escalated_to_staff"
                    await db.commit()
                    await speak(
                        "Sorry, I'm having trouble with that. Let me connect you with a team member."
                    )
                    await wait_until_played()
                    await _escalate_call(call_sid)
                    return

                logger.info("agent [%s]: %s", call_sid, reply)

        transcript_task = asyncio.create_task(handle_transcripts())

        try:
            while True:
                raw = await websocket.receive_text()
                message = json.loads(raw)
                event = message.get("event")

                if event == "media":
                    audio = base64.b64decode(message["media"]["payload"])
                    await transcriber.send_audio(audio)
                elif event == "mark":
                    if not playback_done.done():
                        playback_done.set_result(True)
                elif event == "stop":
                    call.outcome = call.outcome or "handled_by_ai"
                    await db.commit()
                    break
        except WebSocketDisconnect:
            pass
        finally:
            transcript_task.cancel()
            await transcriber.close()
