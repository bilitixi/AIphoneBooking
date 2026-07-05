from fastapi import APIRouter, Depends, Form
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.twiml.voice_response import Gather, VoiceResponse

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
        "purposes. For takeaway orders, press 1. To make, change, or cancel "
        "a reservation, press 2."
    )
    gather = Gather(num_digits=1, action=f"{settings.public_base_url}/phone/gather", method="POST")
    vr.append(gather)
    # If the caller doesn't press anything, repeat once via Twilio's default
    # re-prompt behavior (falls through and hangs up otherwise).
    vr.say("We didn't get your selection. Goodbye.")

    return Response(content=str(vr), media_type="application/xml")
