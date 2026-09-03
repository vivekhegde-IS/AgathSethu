# Member 3 Documentation

## Architecture & Integration

Member 3 implements the **AGHAT SETHU Incident Response Platform**, comprising:

1. **Frontend (`member3/frontend`)**:
   - Modern React 18 + TypeScript + Vite + Tailwind CSS Single Page Application
   - Citizen Portal with Challan Tracking, Receipts, Payment flows, and Vehicle Management
   - Authority Tactical TOC Dashboard with Live Junction Feeds, Camera Map, Violations Dossier, and Analytics
   - Real-time WebSocket connection to backend event stream
   - Direct integration with Member 1 (CARLA crash detection) and Member 2 (Vision ANPR/Collision) via adapter interfaces

2. **Backend (`member3/backend`)**:
   - FastAPI REST API with automatic OpenAPI documentation (`/docs`)
   - SQLAlchemy 2.0 ORM with PostgreSQL 18
   - Alembic database migrations (`alembic/versions/001_initial_schema.py`)
   - JWT authentication (`/api/auth/login`, `/api/auth/register`, `/api/auth/me`)
   - Role-based authorization: `admin`, `authority`, `citizen`

3. **Demonstration & Evaluation**:
   - Default seed data provided via `seed.py`
   - High-resolution ANPR video evidence player integrated into violation detail views
