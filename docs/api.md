# Admin API Reference

This describes the REST API the frontend (staff admin portal) uses to read
and write the database. It is separate from the `/phone/*` webhook routes
Twilio calls and from the AI agent's in-process tools — see
[Authentication boundaries](#authentication-boundaries) below.

Base URL: `{PUBLIC_BASE_URL}` (e.g. `https://your-domain.example.com`)

## Authentication

All `/api/*` routes except `/api/auth/login` require a JWT bearer token.

### Setup

Admin accounts live in the `admin_users` table (not env vars), so more than
one person can have their own login. Each account has a `role`:

- **manager** — full access, and can create/list/update other admin_users.
- **staff** — full access to `/api/reservations`, `/api/customers`,
  `/api/capacity-limits`, `/api/calls`; gets `403` on `/api/admin-users`.

Bootstrap the first (manager) account via CLI, then create the rest through
the API:

```bash
alembic upgrade head
python -m app.scripts.create_admin <username>   # always role=manager, prompts for a password
```

Run the script again with an existing username to reset that admin's
password. There's no self-service signup — the CLI is only for bootstrapping
the first manager; after that, managers create accounts via
`POST /api/admin-users`.

### `POST /api/auth/login`

No auth required.

**Request**

```json
{ "username": "admin", "password": "your-password" }
```

**Response** `200`

```json
{ "access_token": "eyJhbGciOi...", "token_type": "bearer" }
```

`401` if the username/password don't match, or the account is inactive.

Tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default 60). There is no
refresh endpoint — re-login once the token expires.

### Using the token

Send it on every subsequent request:

```
Authorization: Bearer <access_token>
```

Missing or invalid tokens get `401 Unauthorized`.

---

## Admin users — `/api/admin-users`

**Manager role required for every route here** — a `staff` token gets `403`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/admin-users` | List all admin accounts |
| POST | `/api/admin-users` | Create a new admin account |
| PATCH | `/api/admin-users/{id}` | Change role or activate/deactivate |

### Object shape

```json
{
  "id": "uuid",
  "username": "jane",
  "role": "staff",
  "is_active": true
}
```

### `POST /api/admin-users`

```json
{ "username": "jane", "password": "at-least-8-chars", "role": "staff" }
```

`role` is `"manager"` or `"staff"` (defaults to `"staff"` if omitted). `201`
with the created account. `409` if the username is taken, `422` for an
invalid role.

### `PATCH /api/admin-users/{id}`

All fields optional.

```json
{ "role": "manager", "is_active": false }
```

`404` if not found, `422` for an invalid role.

---

## Reservations — `/api/reservations`

| Method | Path | Description |
|---|---|---|
| GET | `/api/reservations` | List reservations, newest `starts_at` first — filterable |
| GET | `/api/reservations/{id}` | Get one reservation |
| POST | `/api/reservations` | Create a reservation |
| PATCH | `/api/reservations/{id}` | Update a reservation |
| DELETE | `/api/reservations/{id}` | Cancel a reservation |

### `GET /api/reservations` query params

All optional, combinable:

| Param | Type | Description |
|---|---|---|
| `date` | `YYYY-MM-DD` | Restaurant-local calendar day (uses `RESTAURANT_TIMEZONE`) — returns reservations whose `starts_at` falls on that day |
| `status` | string | Exact match, e.g. `confirmed`, `cancelled`, `completed`, `no_show` |
| `customer_id` | uuid | Only that customer's reservations |

Example: `GET /api/reservations?date=2026-07-15&status=confirmed`

### Object shape

```json
{
  "id": "uuid",
  "customer_id": "uuid",
  "party_size": 4,
  "starts_at": "2026-07-15T18:30:00+12:00",
  "ends_at": "2026-07-15T20:30:00+12:00",
  "status": "confirmed",
  "source": "staff_portal",
  "special_requests": "window seat if possible"
}
```

### `POST /api/reservations`

**Request**

```json
{
  "customer_id": "uuid",
  "party_size": 4,
  "starts_at": "2026-07-15T18:30:00+12:00",
  "special_requests": "optional"
}
```

`201` with the created reservation. `409` if the slot is full
(`ReservationConflict`).

### `PATCH /api/reservations/{id}`

All fields optional — only what's provided is changed.

```json
{
  "starts_at": "2026-07-15T19:00:00+12:00",
  "party_size": 6,
  "special_requests": "optional"
}
```

`409` on a scheduling conflict, `404` if the reservation doesn't exist.

### `DELETE /api/reservations/{id}`

Cancels the reservation (sets `status`), returns the updated reservation
object. `404` if not found.

---

## Customers — `/api/customers`

| Method | Path | Description |
|---|---|---|
| GET | `/api/customers` | List all customers, newest first |
| GET | `/api/customers/{id}` | Get one customer |
| PATCH | `/api/customers/{id}` | Update a customer |

### Object shape

```json
{
  "id": "uuid",
  "phone_number": "+64211234567",
  "full_name": "Jane Doe",
  "email": "jane@example.com",
  "notes": "prefers booth seating"
}
```

Customers are created automatically by the AI phone agent (or implicitly
via the `customer_id` on a reservation) — there is no `POST` endpoint.

### `PATCH /api/customers/{id}`

All fields optional.

```json
{ "full_name": "Jane Doe", "email": "jane@example.com", "notes": "..." }
```

`404` if not found.

---

## Capacity limits — `/api/capacity-limits`

Staff-defined windows that cap seating below the default capacity (e.g. a
private event). Outside any window, `RESTAURANT_DEFAULT_CAPACITY` applies.
Overlapping windows: the lowest cap wins.

| Method | Path | Description |
|---|---|---|
| GET | `/api/capacity-limits` | List all limits, ordered by `starts_at` |
| POST | `/api/capacity-limits` | Create a limit |
| PATCH | `/api/capacity-limits/{id}` | Update a limit |
| DELETE | `/api/capacity-limits/{id}` | Delete a limit |

### Object shape

```json
{
  "id": "uuid",
  "starts_at": "2026-07-20T00:00:00+12:00",
  "ends_at": "2026-07-20T23:59:00+12:00",
  "max_customers": 20,
  "note": "private event"
}
```

### `POST /api/capacity-limits`

```json
{
  "starts_at": "2026-07-20T00:00:00+12:00",
  "ends_at": "2026-07-20T23:59:00+12:00",
  "max_customers": 20,
  "note": "optional"
}
```

`201` with the created limit.

### `PATCH /api/capacity-limits/{id}`

All fields optional. `404` if not found.

### `DELETE /api/capacity-limits/{id}`

`204` on success, `404` if not found.

---

## Calls — `/api/calls`

Read-only log of inbound phone calls handled by the IVR/AI agent.

| Method | Path | Description |
|---|---|---|
| GET | `/api/calls` | List all calls, newest first |

### Object shape

```json
{
  "id": "uuid",
  "call_sid": "CAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "from_number": "+64211234567",
  "ivr_choice": "2",
  "outcome": "booked",
  "started_at": "2026-07-10T12:00:00+12:00",
  "ended_at": "2026-07-10T12:04:32+12:00"
}
```

---

## Errors

All error responses follow FastAPI's default shape:

```json
{ "detail": "human-readable message" }
```

| Status | Meaning |
|---|---|
| 401 | Missing/invalid/expired token, or bad login credentials |
| 404 | Resource not found |
| 409 | Reservation/capacity conflict |
| 422 | Request body failed validation (wrong types, missing fields) |

---

## Authentication boundaries

This backend has three independent trust boundaries — don't assume they
share auth:

- **`/api/*` (this document)** — JWT bearer token from `/api/auth/login`,
  used by the staff frontend.
- **`/phone/*`** — Twilio webhook signature (`X-Twilio-Signature`), used
  only by Twilio's servers. Not usable from the frontend.
- **AI phone agent → database** — no HTTP layer at all. The agent calls
  Python functions directly in-process during a live call; it never goes
  through `/api/*`.
