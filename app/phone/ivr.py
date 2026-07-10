from fastapi import APIRouter, Depends, Form
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.core.config import get_settings
from app.core.security import verify_twilio_signature
from app.db.models import PhoneCall
from app.db.session import get_db

router = APIRouter(prefix="/phone", tags=["phone"])


@router.post("/gather", dependencies=[Depends(verify_twilio_signature)])
async def gather(
    CallSid: str = Form(...),
    Digits: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
) -> Response:
    settings = get_settings()
    result = await db.execute(select(PhoneCall).where(PhoneCall.call_sid == CallSid))
    call = result.scalar_one_or_none()

    vr = VoiceResponse()

    if call is None or Digits not in ("1", "2"):
        vr.say("Sorry, that wasn't a valid selection. Goodbye.")
        return Response(content=str(vr), media_type="application/xml")

    call.ivr_choice = Digits

    if Digits == "1":
        call.outcome = "transferred_to_staff"
        vr.say("Connecting you to our team for takeaway orders and large group bookings.")
        vr.dial(settings.twilio_staff_number)
    else:
        vr.say("Connecting you to our reservation assistant.")
        ws_base = settings.public_base_url.replace("https://", "wss://").replace("http://", "ws://")
        connect = Connect()
        connect.stream(url=f"{ws_base}/ws/reservation?call_sid={CallSid}")
        vr.append(connect)

    await db.commit()
    return Response(content=str(vr), media_type="application/xml")
