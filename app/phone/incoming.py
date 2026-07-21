from fastapi import APIRouter, Depends, Form
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.core.config import get_settings
from app.core.security import verify_twilio_signature
from app.db.models import PhoneCall
from app.db.session import get_db

router = APIRouter(prefix="/phone", tags=["phone"])


@router.post("/incoming", dependencies=[Depends(verify_twilio_signature)])
async def incoming_call(
    CallSid: str = Form(...),
    From: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> Response:
    db.add(PhoneCall(call_sid=CallSid, from_number=From))
    await db.commit()

    settings = get_settings()
    vr = VoiceResponse()
    vr.say(
        "Welcome to ABC Restaurant. This call may be recorded for quality "
        "purposes. Connecting you to our AI reservation assistant."
    )
    ws_base = settings.public_base_url.replace("https://", "wss://").replace("http://", "ws://")
    connect = Connect()
    connect.stream(url=f"{ws_base}/ws/reservation?call_sid={CallSid}")
    vr.append(connect)

    return Response(content=str(vr), media_type="application/xml")
