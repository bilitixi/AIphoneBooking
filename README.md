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

- `app/voice/transcriber.py` and `app/voice/synthesizer.py` define the
  STT/TTS interfaces but the concrete Deepgram/AssemblyAI/ElevenLabs/Cartesia
  wiring is left as `NotImplementedError` pending the vendor decision in
  design doc §7.1 (prototype latency before committing).
- The reservation exclusion constraint (`schema.sql` / migration `0001`) is
  the actual source of truth for preventing double-booking; app code only
  reacts to it (`ReservationConflict`).
