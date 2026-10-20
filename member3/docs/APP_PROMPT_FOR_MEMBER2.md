# Prompt: Build the AGHAT SETHU App (mirrors the existing website + backend)

> Copy everything below this line into your AI tool / give it to the app developer.

---

You are building the app version of **AGHAT SETHU**, an AI-based **hit-and-run accident detection, vehicle identification and multi-junction tracking** platform for Bengaluru traffic police. A full web app already exists (React 18 + TypeScript + Vite + Tailwind, FastAPI + PostgreSQL backend). The app must have the **same two portals, the same pages, and talk to the same backend API** — do not invent new data or fake numbers; every figure comes from the backend.

## 1. System overview (what the whole project does)

The project has three parts:

1. **Simulation (Member 1 – CARLA 0.9.16)**: a 3-junction road network (J01, J02, J03) in the CARLA simulator.
   - Vehicle **A ("ego")** is driven manually with the keyboard (pygame window: W/S throttle/brake, A/D steer, Space hand brake, Q reverse). Vehicles **B–H** drive on CARLA Traffic Manager autopilot.
   - When A crashes into another vehicle, the hit vehicle is stopped (full brake + hand brake). In the original scripted scenario, A and B collide at J01 and B flees through J02 and J03 — the "hit-and-run".
   - Every vehicle carries a **simulated Indian number plate** (each from a different state, e.g. KA, MH, TN…) drawn on the camera image, and a **simulated FASTag RFID tag (EPC)**.
   - **One camera per junction** streams video. Frames + vehicle bounding boxes go to the backend over WebSocket; H.264 video goes to a MediaMTX server for WebRTC playback.
   - **Simulated IMU (6-axis accelerometer + gyroscope)** on vehicles: crash detection computes acceleration magnitude, G-force, jerk and gyro magnitude, then a hybrid explainable detector raises `CRASH_DETECTED` / `crash_alert` with a confidence score. Ground truth from CARLA's collision sensor is kept separate and never used for detection.
   - **Simulated UHF RFID reader at each junction**: log-distance path-loss RSSI with random shadowing, ~20 Hz inventory rounds, read probability drops with distance, speed and number of competing tags, and one aggregated `TAG_REPORT` per tag per reporting interval (like a real reader — only EPC + RSSI + time window, no plate).
2. **Vision (Member 2)**: vehicle detection (YOLO), tracking, collision-pair scoring, ANPR and cross-junction identity.
3. **Platform (Member 3)**: the FastAPI backend + web portals described below.

### Live data flow
```
CARLA sim ──WebSocket /ws/carla/cameras──► Backend
   messages: camera_frame (JPEG + vehicle boxes), vehicle_boxes (20 Hz),
             rfid_reading (TAG_REPORT), vehicle_state, crash_alert
Backend ──acks crash_alert (crash_alert_ack)──► CARLA (alerts retried until acked)
Backend ──WebSocket /ws/live-cameras──► Portal (frames + events:
             crash_alert, incident_created, watchlist_rfid_hit, vision_match_result)
CARLA ──RTSP H.264──► MediaMTX ──WebRTC (WHEP, signalled via backend)──► Portal
```

## 2. What the backend does (FastAPI, base URL e.g. `http://<host>:8000`, docs at `/docs`)

Auth is **JWT Bearer**. Roles: `citizen`, `authority`, `admin`. Authority accounts need admin approval (status pending → active). All times shown in **IST (Asia/Kolkata)**.

### 2.1 Auth – `/api/auth`
- `POST /register/citizen` — name, email, mobile, password, vehicle registration number.
- `POST /register/authority` — name, official email, badge/service number, jurisdiction/unit, password (account pending approval).
- `POST /login` → JWT. `GET /me`, `PATCH /me` (update name/mobile), `POST /logout`.

### 2.2 Level 1 – Routine violation video pipeline (authority only) – `/api/routine-violations`
- `POST /detect` — authority uploads a traffic video → returns a `job_id`. `GET /jobs/{job_id}` polls status (`queued | processing | completed | failed | cancelled`) and result.
- Pipeline: hardware video decode → YOLO11n (person + motorcycle, OpenVINO on iGPU) → camera-motion compensation → tracking → rider↔bike association → **helmet check** on rider heads → **triple-riding** check (≥3 riders) → merge tracker fragments of the same bike (position/size/heading/appearance) → **plate detection + OCR** (PP-OCRv3 with per-character confidence, character voting across frames, Indian plate format validation & state-code correction) → one evidence image per violating vehicle (red vehicle box, blue plate box, zoomed plate inset, plate text banner).
- Result per vehicle: violations list, plate number, state, plate status (`confirmed | low_confidence | unreadable`), first-violation time, evidence image; plus a summary CSV. Files via `GET /runs/{run}/{file}` and `GET /evidence/{file}` (auth required).
- **Fine generation**: plate is looked up in the `vehicles` table → fine goes to the owning citizen. ₹1000 for NO HELMET, ₹1000 for TRIPLE RIDING. One fine per (plate, violation type) per run. A `fine_issued` notification is written for the citizen.
- Plate not registered / unreadable → `unmatched_violations`. **Partially read plate** → `pending_verification` with a strict pattern like `KA __ AT 3514` and the registered plates that fit; nobody is fined until RFID or an officer resolves it.

### 2.3 Level 2 – Crash incidents + RFID cross-verification (authority only)
- On `crash_alert` the backend creates **one incident per collision** (idempotent: repeated alert ids and new CARLA runs are handled).
- **Crash-zone RFID snapshot**: the RFID reads at the crash junction in the window `t_crash ± 30 s` (event time) identify the tags near the crash → resolved to plates through the EPC→plate registry (unknown tag = `UNREGISTERED_TAG`, never invented).
- Involved tags go on a **watchlist**. A read of a watchlisted tag at a **different junction after the crash** = `watchlist_rfid_hit` → a **sighting** (incident, tag, junction).
- **Blind ANPR verification**: camera frames around the sighting are run through the plate detector + OCR **without being told the RFID plate**; the plate is attached to the suspect only by position inside that vehicle's box. Then compared with the registry plate → status (`vision_match_result`, versioned updates until final).
- **NETRA** (shadow mode): a research algorithm that associates each RFID tag pass to a camera vehicle track using geometry + Sinkhorn confidences, with certified confirmation thresholds (error-rate bounded); it may also answer "tag on no visible vehicle".
- Evidence images stored under `runtime/incident_evidence/<incident>/<junction>/` (best frames by sharpness, plate size, OCR confidence), with sha256 in Postgres.
- `crash_involvement` notifications go to citizens whose registered vehicle is in the crash.
- Endpoints: `GET /api/incidents` (list/paginate), `GET /api/incidents/board` (radar), `GET /api/incidents/{id}` (timeline, snapshot panels, sighting cards), `GET /api/incidents/{id}/tracks` (per suspect: crash zone → junctions), `GET /api/incidents/{id}/evidence/{eid}` (image), `POST /api/incidents/{id}/resolve` (needs password re-entry), `GET /api/rfid/health` (RFID FUSION badge).

### 2.4 Other endpoints
- Authority ops: `GET /api/authority/summary` (dashboard counts + latest crash frame), `GET /api/authority/fines` (list, filter, paginate, revenue by month/year), `GET /api/authority/junctions` (per junction: camera state, crashes, suspect sightings, confirmed count).
- Partial plates: `GET /api/authority/pending-verifications`, `GET .../{id}/snapshot`.
- Cameras: `GET /api/cameras/status` (are frames actually arriving from CARLA).
- WebRTC: `GET /api/streams` (stream list + ICE servers), `POST /api/streams/{path}/whep` (SDP offer → answer), `PATCH`/`DELETE .../whep/{session}`. Video flows directly from MediaMTX; only signalling goes through the backend.
- Citizen: `GET /api/citizen/fines`, `GET /api/citizen/fines/{id}/snapshot`, `GET .../{id}/clip`, `POST /api/citizen/fines/{id}/pay` (method: `upi | card | netbanking`, **simulated gateway** → stores payment with receipt number, marks fine Paid), `GET /api/citizen/payments`, `GET /api/citizen/notifications`, `POST /api/citizen/notifications/{id}/read`, `POST /api/citizen/notifications/read-all`, `GET /api/citizen/incidents/{id}` (only if the citizen's vehicle was involved).
- Evidence images are served only through authenticated endpoints (fetch with the token, then display) — never public URLs.

### 2.5 Database tables (PostgreSQL)
`users`, `vehicles` (owner, plate, make, model, year, colour, type, fastag_id, state), `junctions`, `cameras`, `violations`, `incidents`, `videos`, `fines`, `fine_payments` (method, receipt reference), `unmatched_violations`, `pending_verification`, `notifications` (kind: `crash_involvement | fine_issued`, read_at), plus RFID tables (reads, snapshots, sightings, evidence).

## 3. Public screens
1. **Home / Landing** — only two entry cards: **Citizen Login** and **Authority Login**. A signed-in user goes straight to their own portal.
2. **Citizen Login** (email + password) and **Citizen Sign-up** (full name, email, mobile, vehicle registration number, password, confirm password).
3. **Authority Login** (official email + password; "For authorised traffic police and control-room officers only. Access is logged.") and **Authority Sign-up** (full name, official email, badge/service number, jurisdiction/unit, password, confirm) → "Your officer account is awaiting approval."
4. **Info pages**: Privacy Policy, Terms of Use, Accessibility Statement, Help & Contact.

## 4. Citizen Portal (role `citizen`; sees only their own data)
Navigation: Dashboard · My Vehicles · My Violations · Pay Fines · Payment History · Notifications · Profile Settings.

1. **Dashboard** — "Welcome back, <name>"; stat cards: Registered Vehicles, Fines Issued, Unpaid Fines, Total Unpaid (₹); list of My Registered Vehicles; table of My Violations / Fines.
2. **My Vehicles** — read-only list of vehicles registered to the account (plate, make/model, colour, type, FASTag ID).
3. **My Violations (Traffic e-Challan History)** — all fines newest first: challan no., plate, violation type (NO HELMET / TRIPLE RIDING), amount, date/time, plate status, Paid/Unpaid; view the evidence snapshot image and video clip.
4. **Pay Fines** — unpaid challans with a Pay button, plus payment history.
5. **Pay Fine detail** — fine details + evidence, choose UPI / Debit-Credit card / Net banking → simulated payment → **Payment receipt** with receipt number; the fine becomes Paid everywhere.
6. **Payment History (Receipts)** — every payment: receipt number, challan, amount, method, paid at.
7. **Notifications** — stored alerts, filter tabs (All / Unread / E-challan / Crash), mark one or all as read. Types: "fine issued to your vehicle" and "your vehicle was involved in a crash".
8. **Crash Incident Report** (opened from a crash notification) — reference, time, place, status and vehicles involved only. Camera frames and RFID data stay with the authority.
9. **Profile Settings** — full name, mobile (editable), email; saved via `PATCH /api/auth/me`.

## 5. Authority / Admin Portal – Tactical Operations Centre (roles `authority`, `admin`)
Navigation sections:

**OPERATIONS**
1. **Overview (Dashboard)** — stat cards: Crashes detected, Unresolved crashes, Traffic violations detected, Fines pending; "Recent crashes" list; "Latest crash frame" image; "Violations by type" chart.
2. **Live Camera Feeds** — three tiles J01, J02, J03: WebRTC H.264 live video (fallback: JPEG frames over WebSocket), fullscreen, online/offline status from `/api/cameras/status`. When a crash happens a **CRASH DETECTED popup** appears (junction, position, vehicles, received-at) and the tile shows a crash overlay with the crash time. "View Live Feed" from an incident opens the right junction. **Live Plate Detections** panel shows plates read in real time by live ANPR on the CARLA feed (confirmed / low confidence / unreadable).
3. **Junction Overview** — each junction: camera live state, crashes recorded there, suspect vehicles picked up by RFID after a crash, and how many the camera confirmed.

**LEVEL 1 ENFORCEMENT**
4. **Routine Violations (Level 1)** — "Upload Traffic Video" → progress (queued/processing) → results: per violating vehicle the evidence image (click to enlarge), violations, plate, state, plate status, time in video; download summary CSV. Fines are auto-issued to registered owners.
5. **Fines & Revenue** — cards: Fines issued, Revenue collected, Pending; filter All/Paid/Unpaid; year selector; Annual fines chart (month-wise, IST); fines table.
6. **Partial Plates – Pending Verification** — violations with partly read plates: captured frame (enlarge), pattern like `KA __ AT 3514`, candidate registered plates with scores, status.

**LEVEL 2 CRASH INVESTIGATION**
7. **Crash Incident Radar** — every unresolved crash newest first (junction, time, severity, vehicles); "Resolved today" section cleared at 00:00 IST; **Resolve** action with password re-entry; auto-refresh.
8. **Evidence Records** — all incidents, filter All / Resolved / Unresolved; each row opens the detail page.
9. **Incident Evidence detail** — crash info and involved vehicles; crash-zone RFID snapshot (`t_crash ± 30 s`: tags, plates, peak RSSI, reports); **Next-junction sightings** ("RFID watchlist hits after the crash, verified by the blind ANPR") with per-junction verdict, seen-at time, plate read in this frame, raw OCR, OCR confidence, plate pixel size, overall status; stored evidence images. Updates live on `incident_created`, `watchlist_rfid_hit`, `vision_match_result`.

**VEHICLE INTELLIGENCE** (currently demo/static data on the website)
10. **Vehicle Registry & Search** — search by plate or FASTag; matched vehicle profiles.
11. **Vehicle Profile** — attributes & identity, cross-junction sighting timeline.
12. **Multi-Junction Tracking** — pick a vehicle, see its path J01 → J02 → J03 on a junction map.
13. **Violation Detail** — evidence frame and offence diagnostics.

## 6. App requirements
- Same backend, same endpoints, JWT stored securely; route users by role after login; authority pages blocked for citizens and vice versa.
- Real-time: connect to `/ws/live-cameras` for crash popups and incident updates; push a local notification on a new crash (authority) or new fine/crash notification (citizen).
- Load protected images/videos with the `Authorization: Bearer` header.
- Use rupee (₹) amounts and IST times; government-portal look (navy/blue, white, clean tables, status badges: Paid green, Unpaid red, Pending amber).
- Handle empty, loading and offline states (e.g., "Camera offline – no frames from CARLA").

**Demo accounts**: Admin `admin@trafficops.blr.gov.in` / `Admin@Dev2026` · Inspector `inspector.vikram@trafficops.blr.gov.in` / `Authority@Dev2026` · Citizen `aarav.sharma@example.com` / `Citizen@Dev2026`.
