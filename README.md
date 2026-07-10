# ABC Restaurant Backend

FastAPI backend implementing `backend_design.md`: Twilio phone gateway (IVR +
media streams), a Claude-driven reservation agent, and REST APIs for the
admin portal. Persistence is Postgres (Supabase).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in Twilio / Anthropic / STT / TTS / DB creds
```

Create the database, then run migrations:

```bash
alembic upgrade head
```

Run the app:

```bash
uvicorn app.main:app --reload
```

Run tests (reservation-service tests need a real reachable Postgres — they
skip automatically otherwise):

```bash
pytest
```

## Notes

- `app/voice/transcriber.py` (Deepgram) and `app/voice/synthesizer.py`
  (ElevenLabs) are wired up for real, using mulaw/8kHz in both directions so
  no audio transcoding is needed between Twilio and either vendor. Set
  `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, and `ELEVENLABS_VOICE_ID` in
  `.env`. AssemblyAI/Cartesia are left as stubs if you want to prototype the
  alternative per design doc §7.1.
- Booking is capacity-based, not table-based: a reservation fits if the sum
  of overlapping confirmed party sizes plus the new party stays within the
  effective capacity. That's `RESTAURANT_DEFAULT_CAPACITY` (env, default 50)
  unless a staff-defined `capacity_limits` window overlaps the slot — manage
  those via the `/api/capacity-limits` admin endpoints (lowest cap wins when
  windows overlap). Writers serialize through a Postgres advisory lock in
  `reservation_service`, so concurrent calls can't oversell the last seats.
- The agent never asks callers to pick a table; it asks for any notes
  (allergies, occasions) and stores them on the reservation as
  `special_requests`.
