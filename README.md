# ABC Restaurant Backend

FastAPI backend implementing `backend_design.md`: Twilio phone gateway (media
streams), a Claude-driven reservation agent, and REST APIs for the admin
portal. Persistence is Postgres (Supabase).

## System architecture

A single FastAPI process serves two very different clients: Twilio (inbound
phone calls, over a webhook plus a bidirectional media-stream WebSocket) and
the staff admin portal (JWT-authenticated REST under `/api/*`). Both paths
share the same service layer and Postgres database.

```mermaid
flowchart LR
    caller(["📞 Caller"])
    staff(["🧑‍💼 Staff"])

    subgraph external["External services"]
        twilio["Twilio Voice<br/>(PSTN + Media Streams)"]
        deepgram["Deepgram<br/>(speech-to-text)"]
        eleven["ElevenLabs<br/>(text-to-speech)"]
        claude["Anthropic Claude<br/>(Messages API, streaming + tools)"]
    end

    admin["Admin portal<br/>(Vercel frontend)"]

    subgraph backend["FastAPI backend (app/)"]
        direction TB
        phone["phone/<br/>incoming.py · media_stream.py"]
        voice["voice/<br/>transcriber.py · synthesizer.py"]
        ai["ai/<br/>reservation_agent.py · tools.py · claude_client.py"]
        api["api/<br/>auth · reservations · customers ·<br/>capacity_limits · calls · admin_users"]
        services["services/<br/>reservation_service · customer_service"]
        core["core/<br/>config · security · cron · logging"]
        db_layer["db/<br/>models.py · session.py · migrations"]
    end

    pg[("Postgres<br/>(Supabase)")]

    caller <--> twilio
    twilio -- "POST /phone/incoming" --> phone
    twilio <-->|"WS /ws/reservation<br/>(mulaw 8kHz audio)"| phone
    phone --> voice
    voice <--> deepgram
    voice <--> eleven
    phone --> ai
    ai <--> claude
    ai --> services

    staff --> admin
    admin -- "HTTPS /api/* (JWT)" --> api
    api --> services

    services --> db_layer
    phone --> db_layer
    core -. "daily cleanup task" .-> services
    db_layer <--> pg
```

### Layers

| Layer | Path | Responsibility |
| --- | --- | --- |
| Phone gateway | `app/phone/` | `incoming.py` answers Twilio's voice webhook (signature-verified), logs a `phone_calls` row, and returns TwiML that opens a media stream. `media_stream.py` runs the per-call WebSocket loop: forwards caller audio to STT, feeds final transcripts to the agent, streams TTS audio back, guards against echo, and hangs up or transfers to staff via the Twilio REST API. |
| Voice | `app/voice/` | Pluggable `Transcriber` / `Synthesizer` interfaces. Deepgram (streaming STT) and ElevenLabs (streaming TTS) are implemented; AssemblyAI / Cartesia are stubs. Audio stays mulaw/8kHz end to end, so no transcoding. |
| AI agent | `app/ai/` | `reservation_agent.run_turn` builds the system prompt (date calendar, opening hours, caller ID), streams Claude's reply sentence-by-sentence to TTS, and executes tool calls. `tools.py` defines the tools Claude can call (`find_customer`, `check_availability`, `create_reservation`, `find_reservations`, `modify_reservation`, `cancel_reservation`, `escalate_to_staff`, `end_call`) and pins every call to the caller's own phone number. |
| Admin API | `app/api/` | REST endpoints for the staff portal — see [`docs/api.md`](docs/api.md). JWT auth with `manager` / `staff` roles. |
| Services | `app/services/` | Business rules shared by the agent and the admin API: opening hours, capacity checks (serialized with a Postgres advisory lock), reservation CRUD, customer lookup. `notification_service.py` (SMS/email confirmations) exists but is not currently wired in. |
| Core | `app/core/` | Settings from env (`config.py`), JWT + Twilio signature verification (`security.py`), logging, and the in-process 24h reservation cleanup loop (`cron.py`). |
| Data | `app/db/` | SQLAlchemy async models and session, Alembic migrations. Tables: `customers`, `reservations`, `capacity_limits`, `phone_calls`, `admin_users`. |

### Call flow

```mermaid
sequenceDiagram
    autonumber
    participant C as Caller
    participant T as Twilio
    participant P as phone/ (FastAPI)
    participant S as Deepgram STT
    participant A as ai/reservation_agent
    participant L as Claude
    participant R as services/ + Postgres
    participant V as ElevenLabs TTS

    C->>T: Dials restaurant number
    T->>P: POST /phone/incoming
    P->>R: Insert phone_calls row
    P-->>T: TwiML: Say + Connect/Stream
    T->>P: WS /ws/reservation ("start" event with CallSid)
    P->>V: Greeting (cached after first call)
    V-->>P: Audio
    P-->>T: media events
    loop Each caller turn
        C->>T: Speech
        T->>P: media events (mulaw)
        P->>S: Audio chunks
        S-->>P: Final transcript
        P->>A: run_turn(conversation)
        A->>L: Stream messages + tools
        L-->>A: Text deltas / tool_use
        A->>R: Tool calls (availability, booking, ...)
        R-->>A: Tool results
        A->>V: Each complete sentence
        V-->>P: Audio
        P-->>T: media events back to caller
    end
    alt Request complete
        A-->>P: EndCall → wait for playback mark, hang up
    else Out of scope / error / caller asks for a person
        A-->>P: Escalate → Twilio REST redirects call to staff line (Dial)
    end
```

### Deployment

- **Backend**: deployed to Render. The GitHub Actions workflow
  (`.github/workflows/tests.yml`) runs `pytest` against a Postgres 16 service
  container on every PR and push to `main`; pushes to `main` that pass then
  trigger the Render deploy hook pinned to that commit.
- **Database**: Postgres on Supabase, schema managed by Alembic.
- **Admin frontend**: separate app on Vercel, allowed via
  `CORS_ALLOWED_ORIGINS`.
- **Twilio**: the phone number's voice webhook points at
  `{PUBLIC_BASE_URL}/phone/incoming`.

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

- Reservations older than 7 days (by `starts_at`) are purged automatically:
  the app starts a background task on boot (`app/core/cron.py`) that runs
  the cleanup every 24 hours for as long as the uvicorn process is up, so no
  external scheduler is required. If you'd rather run it from an OS-level
  cron/CronJob instead, `python -m app.scripts.delete_old_reservations` does
  the same cleanup as a one-shot command.

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
- Opening hours are enforced in `reservation_service.closed_reason` and
  configured via env: closed all day on `RESTAURANT_CLOSED_DAYS` (default
  sunday); bookings must start within lunch (`RESTAURANT_LUNCH_OPEN`-
  `RESTAURANT_LUNCH_CLOSE`, default 11:00-14:30) or dinner
  (`RESTAURANT_DINNER_OPEN` through `RESTAURANT_LAST_BOOKING`, default
  17:00-20:45). The agent knows these hours and apologizes instead of
  booking. It also knows upstairs seating is dinner-only and asks for the
  caller's name (stored on the customer record) before booking.
