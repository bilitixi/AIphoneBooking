-- Development seed data: a plausible floor plan for ABC Restaurant.
-- Run after schema.sql / migrations: psql "$DATABASE_URL" -f seed.sql
-- Idempotent: skips tables whose label already exists.

INSERT INTO restaurant_tables (label, seats)
SELECT v.label, v.seats
FROM (VALUES
    ('T1', 2),
    ('T2', 2),
    ('T3', 2),
    ('T4', 4),
    ('T5', 4),
    ('T6', 4),
    ('T7', 6),
    ('T8', 6),
    ('Patio 1', 2),
    ('Patio 2', 4),
    ('Booth 1', 4),
    ('Booth 2', 8)
) AS v(label, seats)
WHERE NOT EXISTS (
    SELECT 1 FROM restaurant_tables t WHERE t.label = v.label
);
