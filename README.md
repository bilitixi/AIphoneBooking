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

Seed the floor plan (without rows in `restaurant_tables`, every availability
check comes back empty and the agent reports "fully booked"):

```bash
psql "$DATABASE_URL" -f seed.sql
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
- The reservation exclusion constraint (`schema.sql` / migration `0001`) is
  the actual source of truth for preventing double-booking; app code only
  reacts to it (`ReservationConflict`).
