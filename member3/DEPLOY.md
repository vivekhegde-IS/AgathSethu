# Deploying AGHAT SETHU (Render + Vercel)

## 1. Backend + database on Render
1. Render dashboard → **New → Blueprint** → connect `vivekhegde-IS/AgathSethu`.
   Render reads `render.yaml` and creates `aghat-sethu-api` (FastAPI) and
   `aghat-sethu-db` (PostgreSQL).
2. It asks for the `sync: false` values:
   - `CORS_ORIGINS`: the Vercel URL (fill in after step 2; `http://localhost:5173` for now)
   - `SEED_AUTHORITY_PASSWORD`, `SEED_CITIZEN_PASSWORD`: the demo logins' passwords
3. After the deploy, check `https://<api>.onrender.com/api/health`.

On first start, `render_start.sh` runs `alembic upgrade head` and seeds the
demo users into the empty database:
- authority: `inspector.vikram@trafficops.blr.gov.in`
- citizen: `aarav.sharma@example.com`

## 2. Frontend on Vercel
1. Vercel → **Add New → Project** → import the repo. Set **Root Directory** to `member3/frontend`
   (Vite is detected automatically).
2. Environment variables:
   ```
   VITE_API_BASE_URL=https://<api>.onrender.com/api
   VITE_WS_URL=wss://<api>.onrender.com/ws
   VITE_LIVE_CAMERA_WS_URL=wss://<api>.onrender.com/ws/live-cameras
   VITE_ENABLE_REAL_AUTH=true
   VITE_ENABLE_MOCK_DATA=true
   VITE_WEBRTC_ENABLED=false
   VITE_APP_ENVIRONMENT=production
   ```
3. Deploy, then set Render's `CORS_ORIGINS` to the Vercel URL (e.g. `https://aghat-sethu.vercel.app`).

## Limits of the free setup
- The free Render service sleeps after 15 min idle; the first request then takes ~1 min.
- Free Render PostgreSQL expires after 30 days (move to Neon or a paid plan to keep data).
- OpenVINO/Ultralytics models are not installed, so routine-violation video
  processing and ANPR do not run; MediaMTX/CARLA live streams are local-only.
- Uploaded/evidence files are lost on each redeploy (no persistent disk on free).
