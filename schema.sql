-- ABC Restaurant — Postgres schema (Supabase)
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- gen_random_uuid()

CREATE TABLE customers (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number  TEXT NOT NULL UNIQUE,
    full_name     TEXT,
    email         TEXT,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Staff-defined windows capping how many customers can be seated at once
-- (e.g. reduced capacity for a private event). Outside any window, the
-- default capacity from app settings (RESTAURANT_DEFAULT_CAPACITY) applies;
-- when windows overlap, the lowest cap wins. Rows are managed through the
-- admin API and can be altered at any time.
CREATE TABLE capacity_limits (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    starts_at     TIMESTAMPTZ NOT NULL,
    ends_at       TIMESTAMPTZ NOT NULL CHECK (ends_at > starts_at),
    max_customers INTEGER NOT NULL CHECK (max_customers >= 0),
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_capacity_limits_time ON capacity_limits(starts_at, ends_at);

CREATE TABLE reservations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id     UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    party_size      INTEGER NOT NULL CHECK (party_size > 0),
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ NOT NULL CHECK (ends_at > starts_at),
    status          TEXT NOT NULL DEFAULT 'confirmed'
                        CHECK (status IN ('confirmed', 'cancelled', 'completed', 'no_show')),
    source          TEXT NOT NULL DEFAULT 'ai_call'
                        CHECK (source IN ('ai_call', 'staff_portal', 'takeaway_transfer')),
    special_requests TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Capacity (sum of party_size over overlapping confirmed reservations vs the
-- effective limit) can't be enforced by a table constraint; writers serialize
-- through pg_advisory_xact_lock in reservation_service instead.
CREATE INDEX idx_reservations_customer ON reservations(customer_id);
CREATE INDEX idx_reservations_time ON reservations(starts_at, ends_at);

CREATE TABLE admin_users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'manager' CHECK (role IN ('manager', 'staff')),
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE phone_calls (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_sid      TEXT NOT NULL UNIQUE,
    from_number   TEXT NOT NULL,
    ivr_choice    TEXT,                    -- '1' = takeaway, '2' = reservation
    outcome       TEXT
                      CHECK (outcome IN (
                          'transferred_to_staff', 'handled_by_ai',
                          'escalated_to_staff', 'abandoned'
                      )),
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at      TIMESTAMPTZ
);
