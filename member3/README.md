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
python -m venv .venv
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

## Demo Credentials

| Role | Email | Password |
|---|---|---|
| Admin | `admin@trafficops.blr.gov.in` | `Admin@Dev2026` |
| Authority Inspector | `inspector.vikram@trafficops.blr.gov.in` | `Authority@Dev2026` |
| Citizen | `aarav.sharma@example.com` | `Citizen@Dev2026` |

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
