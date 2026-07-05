-- ABC Restaurant — Postgres schema (Supabase)
-- Requires btree_gist for the exclusion constraint that prevents double-booking a table.
CREATE EXTENSION IF NOT EXISTS btree_gist;
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

CREATE TABLE restaurant_tables (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label         TEXT NOT NULL,          -- e.g. "T4", "Patio 2"
    seats         INTEGER NOT NULL CHECK (seats > 0),
    active        BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reservations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id     UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    table_id        UUID NOT NULL REFERENCES restaurant_tables(id) ON DELETE RESTRICT,
    party_size      INTEGER NOT NULL CHECK (party_size > 0),
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ NOT NULL CHECK (ends_at > starts_at),
    status          TEXT NOT NULL DEFAULT 'confirmed'
                        CHECK (status IN ('confirmed', 'cancelled', 'completed', 'no_show')),
    source          TEXT NOT NULL DEFAULT 'ai_call'
                        CHECK (source IN ('ai_call', 'staff_portal', 'takeaway_transfer')),
    special_requests TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Prevents two overlapping reservations on the same table at the DB level,
    -- regardless of how many app workers are racing to insert.
    EXCLUDE USING gist (
        table_id WITH =,
        tstzrange(starts_at, ends_at) WITH &&
    ) WHERE (status = 'confirmed')
);

CREATE INDEX idx_reservations_customer ON reservations(customer_id);
CREATE INDEX idx_reservations_table_time ON reservations(table_id, starts_at);

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

CREATE TABLE call_logs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id       UUID NOT NULL REFERENCES phone_calls(id) ON DELETE CASCADE,
    role          TEXT NOT NULL CHECK (role IN ('caller', 'agent', 'tool')),
    content       TEXT NOT NULL,
    tool_name     TEXT,                    -- set when role = 'tool'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_call_logs_call ON call_logs(call_id, created_at);
