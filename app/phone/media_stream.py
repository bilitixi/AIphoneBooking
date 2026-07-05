import asyncio
import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from twilio.rest import Client as TwilioClient

from app.ai.reservation_agent import Escalate, run_turn
from app.core.config import get_settings
from app.db.models import CallLog, PhoneCall
from app.db.session import async_session_factory
from app.voice.synthesizer import create_synthesizer
from app.voice.transcriber import create_transcriber

logger = logging.getLogger(__name__)
router = APIRouter()


async def _log(db, call_id, role: str, content: str, tool_name: str | None = None) -> None:
    db.add(CallLog(call_id=call_id, role=role, content=content, tool_name=tool_name))
    await db.commit()


async def _escalate_call(call_sid: str) -> None:
    """Redirects the live call to the staff line — same <Dial> path used for
    takeaway transfers. Done via the REST API since we can't return TwiML
    over an already-connected media stream."""
    settings = get_settings()
    client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    twiml = f'<Response><Say>Connecting you to a team member.</Say><Dial>{settings.twilio_staff_number}</Dial></Response>'
    client.calls(call_sid).update(twiml=twiml)


@router.websocket("/ws/reservation")
async def reservation_media_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    call_sid = websocket.query_params.get("call_sid")

    transcriber = create_transcriber()
    synthesizer = create_synthesizer()
    conversation: list[dict] = []
    stream_sid: str | None = None

    async with async_session_factory() as db:
        result = await db.execute(select(PhoneCall).where(PhoneCall.call_sid == call_sid))
        call = result.scalar_one_or_none()
        if call is None:
            await websocket.close(code=1008)
            return

        caller_phone_number = call.from_number

        async def handle_transcripts():
            nonlocal conversation
            async for transcript in transcriber.finalized_transcripts():
                await _log(db, call.id, "caller", transcript)
                conversation.append({"role": "user", "content": transcript})

                try:
                    reply, conversation = await run_turn(db, caller_phone_number, conversation)
                except Escalate as esc:
                    await _log(db, call.id, "agent", f"[escalating: {esc.reason}]")
                    call.outcome = "escalated_to_staff"
                    await db.commit()
                    await _escalate_call(call_sid)
                    return

                await _log(db, call.id, "agent", reply)
                async for audio_chunk in synthesizer.stream(reply):
                    if stream_sid:
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": base64.b64encode(audio_chunk).decode()},
                                }
                            )
                        )

        transcript_task = asyncio.create_task(handle_transcripts())

        try:
            while True:
                raw = await websocket.receive_text()
                message = json.loads(raw)
                event = message.get("event")

                if event == "start":
                    stream_sid = message["start"]["streamSid"]
                elif event == "media":
                    audio = base64.b64decode(message["media"]["payload"])
                    await transcriber.send_audio(audio)
                elif event == "stop":
                    call.outcome = call.outcome or "handled_by_ai"
                    await db.commit()
                    break
        except WebSocketDisconnect:
            pass
        finally:
            transcript_task.cancel()
            await transcriber.close()
