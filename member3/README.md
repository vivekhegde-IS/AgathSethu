# Member 3 — AGHAT SETHU Traffic Safety Platform

## Overview

Member 3 owns the **full-stack web application** for the AGHAT SETHU hit-and-run detection and traffic safety system. This includes:

- **Citizen Portal** — vehicle registration, violation tracking, payments, notifications
- **Authority Tactical TOC** — live camera feeds, incident management, ANPR evidence, challan issuance
- **FastAPI Backend** — PostgreSQL, JWT authentication, REST API
- **Member Integrations** — frontend adapters for Member 1 (CARLA crash detection) and Member 2 (ANPR/vision pipeline)

---

## Structure

```
member3/
├── frontend/               # React 18 + TypeScript + Vite + Tailwind CSS
│   ├── src/
│   │   ├── api/            # Axios API client
│   │   ├── components/     # Reusable UI components
│   │   │   ├── auth/
│   │   │   ├── authority/
│   │   │   ├── citizen/
│   │   │   ├── layout/
│   │   │   ├── public/
│   │   │   └── ui/
│   │   ├── hooks/          # Custom React hooks
│   │   ├── integrations/
│   │   │   ├── member1/    # CARLA crash-detection adapter
│   │   │   ├── member2/    # ANPR/vision adapter
│   │   │   └── member3/    # RFID/FASTag adapter
│   │   ├── pages/
│   │   │   ├── authority/  # TOC dashboard pages
│   │   │   ├── citizen/    # Citizen portal pages
│   │   │   └── public/     # Public-facing pages
│   │   ├── routes/         # React Router configuration
│   │   ├── services/       # Auth guards, WebSocket
│   │   ├── stores/         # Zustand state stores
│   │   ├── theme/          # Design tokens
│   │   ├── types/          # TypeScript interfaces
│   │   └── utils/
│   ├── public/
│   │   └── evidence/       # Static evidence assets (served by Vite)
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   └── .env.example
│
├── backend/                # FastAPI + SQLAlchemy + Alembic + PostgreSQL
│   ├── alembic/            # Database migrations
│   ├── app/
│   │   ├── core/           # config.py, database.py, security.py
│   │   ├── dependencies/   # FastAPI dependency injection
│   │   ├── models/         # SQLAlchemy ORM models
│   │   ├── routers/        # API route handlers
│   │   ├── schemas/        # Pydantic request/response schemas
│   │   └── services/       # Business logic
│   ├── requirements.txt
│   ├── seed.py             # Demo data seeder
│   └── .env.example
│
├── media/                  # Evidence media (excluded from git — too large)
│   ├── evidence/           # Violation evidence videos
│   └── videos/             # Camera recordings
│
└── README.md
```

---

## Technology Stack

### Frontend
| Technology | Version | Purpose |
|---|---|---|
| React | 18.3 | UI framework |
| TypeScript | 5.3 | Type safety |
| Vite | 5.0 | Build tool & dev server |
| Tailwind CSS | 3.4 | Utility-first styling |
| React Router | 6.20 | Client-side routing |
| Zustand | 4.4 | State management |
| Axios | 1.6 | HTTP client |

### Backend
| Technology | Version | Purpose |
|---|---|---|
| FastAPI | 0.115 | REST API framework |
| SQLAlchemy | 2.0 | ORM |
| Alembic | 1.13 | Database migrations |
| psycopg (v3) | 3.3 | PostgreSQL driver |
| passlib + bcrypt | 1.7 / 4.2 | Password hashing |
| python-jose | 3.3 | JWT tokens |
| Pydantic | 2.9 | Data validation |

### Database
- **PostgreSQL 18** (locally installed)
- Database name: `Aghat_Sethu`
- Connection: `postgresql+psycopg://postgres:PASSWORD@localhost:5432/Aghat_Sethu`

---

## Quick Start

### 1. Backend

```bash
cd member3/backend
py -3.11 -m venv .venv       # Python 3.11 is required for the pinned wheels
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

# Configure environment
copy .env.example .env
# Edit .env with your PostgreSQL password and JWT secret

# Run migrations
python -m alembic upgrade head

# Seed demo data
python seed.py

# Start API server
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API docs: http://localhost:8000/docs

### 2. Frontend

```bash
cd member3/frontend
npm install

# Configure environment
copy .env.example .env
# Edit .env if needed (defaults work for local dev)

npm run dev
```

App: http://localhost:5173

---

## Live Camera Streaming (WebRTC)

The Live page plays the three CARLA junction cameras as **H.264 over WebRTC**:

- **Simulator (`member1/streaming`):** encodes each camera with FFmpeg (NVENC or x264, zero-latency, 1 s GOP) and pushes it over RTSP to **MediaMTX** (`media-server/`) on the website machine.
- **Browser:** opens each stream with WHEP, signalled through the backend (`/api/streams/{cam}/whep`, website login required). Media goes directly from MediaMTX over UDP.
- **Unchanged:** the JPEG WebSocket feed still serves RFID/ANPR and is the tile fallback.

Setup, run order, verification and troubleshooting: [media-server/README-STREAMING.md](media-server/README-STREAMING.md).

## Demo Credentials

| Role | Email | Password |
|---|---|---|
| Admin | `admin@trafficops.blr.gov.in` | `Admin@Dev2026` |
| Authority Inspector | `inspector.vikram@trafficops.blr.gov.in` | `Authority@Dev2026` |
| Citizen | `aarav.sharma@example.com` | `Citizen@Dev2026` |

---

## Live Dashboards: CARLA Fleet Accounts, Crash Text Messages, Google Sign-in

The 8 CARLA cars (A–H) each have an owner account, and one Traffic Control Room
authority account exists. The authority dashboard (`/authority`) and any number
of owner dashboards (`/me`) can be open **side by side in the same browser**, and
fines, crashes and review decisions appear in all of them live.

### Demo accounts

Run `python seed_demo_fleet.py` (in `member3/backend`). It is idempotent: a second
run updates rows in place and never duplicates them. Passwords are read from
**`demo_credentials.local.md`** in the repo root. That file is gitignored, holds
the plaintext demo logins, and is the only place they exist. The database stores
only bcrypt hashes. Owners get placeholder phone numbers (`+9100000000NN`).

| Car | Plate | RFID EPC | Owner (username) |
|---|---|---|---|
| A (ego, human driver) | KA 01 AT 4521 | E200001722110101A0B1 | Arjun Rao (`arjun.rao`) |
| B | MH 12 BR 7814 | E200001722110102A0B2 | Siddharth Kulkarni (`siddharth.kulkarni`) |
| C | TN 09 CK 2365 | E200001722110103A0B3 | Karthik Subramanian (`karthik.subramanian`) |
| D | KL 07 DL 9182 | E200001722110104A0B4 | Anjali Nair (`anjali.nair`) |
| E | DL 03 EN 6047 | E200001722110105A0B5 | Rohit Malhotra (`rohit.malhotra`) |
| F | GJ 05 FP 3419 | E200001722110106A0B6 | Priya Patel (`priya.patel`) |
| G | AP 16 GQ 8273 | E200001722110107A0B7 | Venkata Sai Reddy (`venkata.reddy`) |
| H | TG 08 HR 5196 | E200001722110108A0B8 | Sravani Goud (`sravani.goud`) |
| Authority | — | — | Traffic Control Room (`authority.admin`), username + password only |

**CARLA actor → vehicle:** `backend/app/core/fleet.py` is the single map. CARLA
actor ids change every run, so they are never used. Every v1.8 `crash_alert` /
`vehicle_state` message already carries the car's RFID `epc` (from the script's
`_epc_for`), its letter (`vehicle_id`) and its `plate_number`. The backend
resolves the EPC first, and also accepts a `role_name` of `aghat_vehicle_<letter>`.
Identifiers that disagree resolve to nothing; the backend never guesses. That
gives exactly one `vehicles` row (`carla_letter`, `rfid_epc`) and so one owner.

### How it fits together

- **Per-tab sessions.** The JWT lives in `sessionStorage`, which each tab has its
  own copy of. It is sent as a Bearer header and as the first message on
  `/ws/events`. Logging in as the authority in one tab therefore never logs out
  an owner in another tab. A new tab starts logged out.
- **Live events.** `/ws/events` uses FastAPI's own WebSockets (no second
  framework). The server puts each socket in `authority` (sees everything) or
  `user:<id>` (only that owner's events), based on the verified token; the client
  cannot choose. Every change is committed to PostgreSQL first, then broadcast as
  one of: `fine.issued`, `fine.updated`, `crash.detected`, `crash.partner_named`,
  `hit_and_run.detected`, `notification.created`, `review.updated`. On page load
  and on every reconnect (backoff from 1 s up to 30 s), the page reloads its state
  over REST: `GET /api/me/overview` or `GET /api/authority/live`.
- **Crash → text message.** `/ws/carla/cameras` (live CARLA, the replay tool and
  `tools/simulate_events.py`) calls `services/crash_notify.py` after acking each
  alert. A crash raised by a car's **own** sensors immediately texts its owner:
  *"Crash detected for your vehicle KA 01 AT 4521 at <time>, <location>. Are you
  safe? Emergency: 112."* The owner sees it in a phone-style panel, plus a toast
  and an unread badge. It is sent once per vehicle per incident: re-emits within
  `CRASH_NOTIFY_COOLDOWN_S` (default 120 s) are merged.
- **Review gating (from the paper).** A partner naming
  (`COLLISION_EVENT_CONFIRMED_PARTNER_ASSOCIATION`, or a pair alert's
  `collision_partner`) and a hit-and-run (`vehicle_state` with `escape_confirmed`)
  go **only** to the authority's Review queue. The accused owner is told nothing,
  and no fine is created. The struck car's owner sees only *"Another vehicle may
  have been involved; under review."* **Confirm** tells both owners; **Reject**
  closes the review for the struck owner. Fines are always issued by hand. The
  RFID writer no longer sends owner notifications itself.
- **SMS providers.** `services/sms.py` provides `ConsoleSmsProvider` (the default:
  logs and stores the message) and `TwilioSmsProvider`, which is used only when
  `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_FROM_NUMBER` are all set.
  Placeholder numbers are never sent to a real provider.

### Running backend, dashboards and CARLA together

```bash
# 1. Backend (port 8000)
cd member3/backend
python -m alembic upgrade head          # adds migration 009
python seed_demo_fleet.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. Dashboards
cd member3/frontend && npm run dev      # http://localhost:5173

# 3a. CARLA (v1.8 script unchanged): point it at this backend
set CARLA_EVIDENCE_WS=ws://127.0.0.1:8000/ws/carla/cameras
python vivek_fb_rfid.py

# 3b. ...or no CARLA at all
python tools/simulate_events.py fine           # (a) authority fines car C
python tools/simulate_events.py crash-single   # (b) single-vehicle crash of A
python tools/simulate_events.py crash-pair     # (c) A-B crash, B leaves (hit-and-run)
python tools/simulate_events.py all --pause 8  # all three
```

The two crash scenarios both involve car A. To have (b) and (c) send Arjun two
separate texts, start the backend with `CRASH_NOTIFY_COOLDOWN_S=5`. Otherwise
they count as one incident within 120 s.

### Watching it live (two tabs, same browser)

1. Tab 1: open http://localhost:5173/authority/login and sign in as `authority.admin`.
   You land on **/authority** (Control room).
2. Tab 2: open http://localhost:5173/citizen/login and sign in as `arjun.rao`
   (password or **Sign in with Google**). You land on **/me**.
   Optional: Tab 3 as `karthik.subramanian` (car C).
3. Issue a fine to car C (in the Control room, or with `simulate_events.py fine`).
   It appears instantly in the authority's fine list and on Karthik's `/me`, with
   a toast. When Karthik pays or disputes it, the authority sees the status change live.
4. Run `simulate_events.py crash-single`. Arjun's phone panel shows the text message,
   with a toast and an unread badge. The authority gets the crash alert.
5. Run `simulate_events.py crash-pair`. The authority's Review queue shows
   "Partner named" and "Hit-and-run" for MH 12 BR 7814, with the decision route.
   Arjun sees "under review"; Siddharth (car B) sees nothing. After **Confirm**,
   both owners are told.

### Sign in with Google (vehicle owners only)

**Flow:** OpenID Connect authorization-code flow run by the backend, with PKCE
(S256), a single-use `state` (10 min) and a `nonce`. The backend swaps the code
for an ID token and verifies it with Google's `google-auth` library: signature,
`aud == GOOGLE_CLIENT_ID`, `iss`, expiry, `email_verified` and nonce. Users are
matched on Google's `sub`, never on email.

**Returning the session to the right tab:** the callback redirects the browser to
`/auth/google/done?handoff=…`. The hand-off code is single use, expires after
2 minutes, and is bound to a random value the starting tab kept in its
`sessionStorage`, so only that tab can redeem it. Redeeming it returns the
**same** session token as password login.

**Rules:**
- No open sign-up: a Google account that is not linked to one of the 8 owners
  gets *"No vehicle is linked to this Google account"* and no session.
- A `sub` linked to an authority account is refused with 403.
- The authority login page has no Google button, and the link and unlink
  endpoints reject authority users.

**Linking:**
- Sign in once with username + password, then click **Link Google account** on
  `/me`. **Unlink Google** is on the same page.
- Optional demo pre-link: `GOOGLE_OWNER_LINKS=arjun.rao=you@gmail.com`. It is
  matched once on a verified email, then stored and used as the `sub`.

**Setup in Google Cloud Console:**

1. **APIs & Services → OAuth consent screen**: set User type to *External* and
   leave Publishing status as **Testing**. Under **Test users**, add the Gmail
   accounts you will link. Only these accounts can sign in while the app is in
   Testing.
2. **Credentials → Create credentials → OAuth client ID**, Application type
   **Web application**:
   - Authorised JavaScript origins: `http://localhost:5173`
   - Authorised redirect URIs: `http://localhost:8000/api/auth/google/callback`
     (use the backend's port; if you run it on 8001, use 8001 here and in the env).
3. Put the values in `member3/backend/.env`. Never commit them.
   ```
   GOOGLE_CLIENT_ID=...apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
   SITE_URL=http://localhost:5173
   ```
   Restart the backend. If these variables are empty, the Google button stays
   hidden and password login works as before.

### Tests

The tests need a PostgreSQL database whose name ends in `_test`. They seed their
own test passwords and never use the real demo ones.

```bash
cd member3/backend
set DATABASE_URL=postgresql+psycopg://postgres:<pw>@localhost:5432/aghat_sethu_test
python -m alembic upgrade head
python -m pytest tests -q
```

- `tests/test_accounts_live.py`: seed idempotency, username login, owner isolation
  over REST and `/ws/events`, the live fine flow (issue, dispute, uphold, pay),
  crash → SMS mapping, dedup, review gating, and the real `/ws/carla/cameras`
  ingest path.
- `tests/test_google_auth.py`: real RS256 ID tokens checked by Google's own
  verifier, with the certificate fetch mocked and no network access. Covers:
  linked owner, unlinked account, authority with a linked `sub`, bad
  audience/issuer/nonce, expired token, unverified email, forged signature,
  wrong or reused `state`, wrong tab, link/unlink, the allowlist, and a
  Google-session owner's REST + socket isolation.

---

## Member Integrations

Member 3 integrates with Member 1 and Member 2 via **frontend adapter contracts** located at:

```
frontend/src/integrations/
├── member1/    # Reads CARLA crash-detection events
├── member2/    # Reads ANPR + collision detection events
└── member3/    # RFID/FASTag sensor-fusion adapter
```

These adapters support both **mock mode** (demo) and **real mode** (live member services).

Set in `frontend/.env`:
```env
VITE_ENABLE_MOCK_DATA=true   # false = connect to real member services
VITE_ENABLE_REAL_AUTH=true   # false = mock authentication
```

---

## Media Files

Large video files (`*.mp4`) are excluded from git due to GitHub's file size limits.

Place them locally at:
```
member3/media/evidence/violation_video.mp4
member3/media/videos/camera_junction_1_v22_final_visible_anpr_recording.mp4
```

The frontend serves evidence videos from `frontend/public/evidence/`.

---

## Notes

- Do **not** commit `.env` files (they contain real database passwords and JWT secrets)
- Do **not** commit `node_modules/` or `dist/`
- The `alembic/versions/` migration files **must** be committed — they define the schema
