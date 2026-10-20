# Live camera streaming: H.264 over WebRTC

The three CARLA junction cameras reach the Live page as **H.264 over WebRTC**,
measured at 76 ms (p50) / 110 ms (p95) from encoder input to decoded frame on
this machine, plus the browser's display time.

## Architecture

```
CARLA machine                              website machine (100.118.103.8)
───────────────                            ───────────────────────────────────────────
full_run.py ─ render + plate overlay
   │  streamer.submit()  (O(1), newest frame wins, never blocks the tick)
   ▼
member1/streaming/h264_streamer.py
   3 × [thread + FFmpeg]  bgr24 → I420/NV12 → H.264
   NVENC or x264 zerolatency, constrained baseline, no B-frames,
   1 s GOP, CBR / VBV-limited, 30 fps CFR (sim is 20 Hz)
   │
   └──── RTSP/TCP :8554 (user carla) ────►  MediaMTX  (cam1, cam2, cam3)
                                              │  WHEP on 127.0.0.1:8889 (user website)
                                              ▼
                                           FastAPI  /api/streams/{cam}/whep
                                              │  checks the website JWT (authority/admin)
                                              ▼
                     browser  ◄══ SRTP/UDP :8189 (media direct from MediaMTX) ══
                     Live page: 3 × <video>  (WhepPlayer, H.264 preferred)

full_run.py ─ JPEG camera_frame over WebSocket (unchanged, 5 fps)
   └──► backend: RFID cross-verification / live ANPR, and the Live page fallback image
```

**Why a media server (option a) and not WebRTC straight from the simulator (option b):**
- **Multiple viewers:** the simulator encodes each camera once and MediaMTX fans it
  out. With direct WebRTC the CARLA machine would re-encode, or at least run
  ICE/DTLS/SRTP, for every viewer, competing with the simulation.
- **A stable endpoint:** CARLA can restart (`overridePublisher`) while viewers keep
  one address and reconnect automatically.
- **Separation:** the simulator only needs FFmpeg and an outbound TCP connection.
  Auth, ICE and TURN all stay on the website side.
- **Cost:** one extra hop (a few ms on the same machine) and one more process to run.

Things that are deliberately unchanged:
- **The JPEG WebSocket feed** still runs: RFID cross-verification needs JPEG frames.
- **Simulation and rendering logic, and the MP4 recording.**
- **The Live page layout, badges and crash overlay.**

## Files

| | |
|---|---|
| `member1/streaming/h264_streamer.py` | **new**: encoder module (config, NVENC/x264 choice, pacing, restart) |
| `member1/streaming/__init__.py`, `streaming.env.example` | **new** |
| `member1/full_run.py` | **changed**: create streamer, `submit()` after the plate overlay, `close()` on exit |
| `member3/media-server/mediamtx.yml` | **new**: MediaMTX v1.21 config (cam1-3, auth, WebRTC) |
| `member3/media-server/run_mediamtx.ps1`, `docker-compose.yml`, `.env.example`, `turnserver.conf` | **new** |
| `member3/backend/app/routers/webrtc_streams.py` | **new**: WHEP proxy + `GET /api/streams` |
| `member3/backend/app/core/config.py`, `app/main.py`, `.env.example` | **changed**: settings, router, CORS `expose_headers` |
| `member3/frontend/src/services/webrtc/whepPlayer.ts` | **new**: WHEP player (status, backoff, H.264 pref, stats, teardown) |
| `member3/frontend/src/components/authority/WebRtcCameraVideo.tsx` | **new**: tile video + status, stats, fullscreen |
| `member3/frontend/src/pages/authority/Live.tsx` | **changed**: tiles use `WebRtcCameraVideo`; JPEG is the fallback |
| `member3/frontend/.env.example` | **changed**: `VITE_WEBRTC_ENABLED` |

## Install

**CARLA machine**
- **FFmpeg on PATH**, or set `STREAM_FFMPEG`:
  - Windows: the gyan.dev "full" build (includes `h264_nvenc` and `libx264`).
  - Linux: `sudo apt install ffmpeg`, or a build with `--enable-nvenc` for NVIDIA GPUs.
- **Check NVENC:** `ffmpeg -hide_banner -encoders | findstr nvenc`. The module also test-encodes one frame on startup; without a usable NVIDIA GPU it uses x264.
- **No new Python packages:** it only uses numpy and OpenCV, which are already needed.

**Website machine**
- **MediaMTX v1.21.1:**
  - native: download `mediamtx_v1.21.1_windows_amd64.zip` from
    https://github.com/bluenviron/mediamtx/releases and put `mediamtx.exe` in `member3/media-server/`
    (verify it against `checksums.sha256`);
  - or Docker: `docker compose --env-file .env up -d` in `member3/media-server`.
- **Secrets:** copy `member3/media-server/.env.example` to `.env` and set both passwords.
  - Put the reader password in `member3/backend/.env` as `MEDIAMTX_READ_PASS`.
  - Put the publisher password on the CARLA machine as `STREAM_PUBLISH_PASS`.
- **Firewall (admin PowerShell):**
  ```powershell
  New-NetFirewallRule -DisplayName "MediaMTX RTSP ingest" -Direction Inbound -Protocol TCP -LocalPort 8554 -Action Allow
  New-NetFirewallRule -DisplayName "MediaMTX WebRTC media" -Direction Inbound -Protocol UDP -LocalPort 8189 -Action Allow
  ```
- **No new backend packages:** `httpx` is already in `requirements.txt`. Nothing new for the frontend either.

## Run order

1. **MediaMTX** (website machine): `cd member3\media-server; .\run_mediamtx.ps1`
2. **Backend:** `cd member3\backend; .\start_backend.ps1 -Port 8001`
3. **Frontend:** `cd member3\frontend; npm run dev`
4. **Simulator** (CARLA machine):
   ```powershell
   $env:STREAM_RTSP_BASE = "rtsp://100.118.103.8:8554"
   $env:STREAM_PUBLISH_USER = "carla"
   $env:STREAM_PUBLISH_PASS = "<publisher password>"
   python full_run.py
   ```
   Look for `[STREAM] H.264 encoder: nvenc|x264` and `[STREAM camN] encoding 1280x720@30`.
5. **Viewer:** log in at `/authority/login` and open **Live Camera Feeds**. Each tile shows `WEBRTC` once its video is live.

The order is flexible. Each piece retries:
- the encoders reconnect to MediaMTX with backoff;
- the players retry while a camera is `STREAM OFFLINE`, and recover from `RECONNECTING`;
- until WebRTC is live, the tile shows the JPEG frame, labelled `· JPEG`.

## Verify

- **H.264 is in use:**
  - Open `chrome://webrtc-internals`, then the session's `inbound-rtp (video)`: `codec` = `video/H264 ... profile-level-id=42e01f`.
  - Or click **STATS** on a tile: it shows `H264 (42e01f)`.
  - MediaMTX logs `is reading from path 'camN', 1 track (H264)`.
- **Glass-to-glass latency:**
  1. Start the simulator with `$env:STREAM_DEBUG_OVERLAY = "1"`. Each frame then shows `wall NNNNN` (sim machine clock, ms mod 100000) next to the sim time and frame number.
  2. Click **STATS** on a tile. It shows `viewer wall NNNNN`.
  3. Take one screenshot. Latency = viewer wall − burned-in wall.
  4. Across two machines this needs synced clocks (Windows time sync, or both on Tailscale). Check with `w32tm /stripchart /computer:<other>`.
- **Load:**
  - CARLA machine: Task Manager shows the three `ffmpeg.exe` processes; `nvidia-smi dmon -s u` shows the `enc` column for NVENC.
  - Measured here with x264 veryfast 720p30 at 3 Mbps: about 0.6–0.8 core per camera.
  - Browser: `chrome://media-internals` shows a hardware decoder (`D3D11VideoDecoder` / `VDAVideoDecoder`).

## Configuration

**Simulator** (environment variables; see `member1/streaming/streaming.env.example`):
- `STREAM_FPS` (default 30): keep it above the 20 Hz CARLA camera rate. At an equal rate the two clocks alias and drop frames; measured: 70–89 drops per 445 frames at 20 fps vs 1–4 at 30 fps.
- `STREAM_BITRATE_KBPS` (default 3000).
- `STREAM_WIDTH` / `STREAM_HEIGHT` (0 = native).
- `STREAM_ENCODER` (`auto` / `nvenc` / `x264`).
- `STREAM_X264_PRESET`.
- `STREAM_CAMERAS` (`1:cam1,...`).
- `STREAM_ENABLED=0` turns streaming off.

**Backend** (`member3/backend/.env`):
- `WEBRTC_ENABLED`
- `MEDIAMTX_WHEP_URL`
- `MEDIAMTX_READ_USER` / `MEDIAMTX_READ_PASS`
- `WEBRTC_STREAMS` (`J01:cam1,...`)
- `WEBRTC_ICE_SERVERS` (JSON)

**Frontend:** `VITE_WEBRTC_ENABLED=false` returns to JPEG-only tiles.

## STUN / TURN

- **LAN and Tailscale:** MediaMTX's host candidates (all interfaces plus `webrtcAdditionalHosts`) are directly reachable, so STUN is optional and TURN is not used.
- **Public internet:** viewers behind symmetric NAT or firewalls that block UDP need TURN. Run coturn with `turnserver.conf` and add it to both `WEBRTC_ICE_SERVERS` (browsers) and `webrtcICEServers2` (MediaMTX). The details are in that file.
- **HTTPS:** a production site served over the internet should use HTTPS anyway. A receive-only `RTCPeerConnection` does not need a secure context (only camera/microphone capture does), so plain `http://` works on the LAN and Tailscale.

## Security

- **Signalling:** WHEP signalling needs the website login (authority/admin, the same rule as the Live page), checked by the backend.
- **MediaMTX HTTP:** it listens only on loopback; the reader account is limited to `127.0.0.1` and to `cam1`–`cam3`.
- **Publishing:** only the `carla` account can publish, and only `cam1`–`cam3`. Every other MediaMTX server (HLS, RTMP, SRT, MoQ, API) is off.
- **Passwords:** they live only in `.env` files, which are gitignored. `mediamtx.yml` holds placeholders, overridden through `MTX_AUTHINTERNALUSERS_n_PASS`.

## Troubleshooting

| Symptom | Check |
|---|---|
| Tile stays `STREAM OFFLINE` | The simulator isn't publishing: check its `[STREAM]` lines, the MediaMTX log, and that `STREAM_RTSP_BASE` is reachable (TCP 8554 open). A wrong `STREAM_PUBLISH_PASS` shows as `authentication failed` in MediaMTX. |
| `CONNECTING` forever / ICE `failed` | UDP 8189 is blocked, or MediaMTX advertises an address the viewer can't reach. Add this machine's Tailscale/LAN IP to `MTX_WEBRTCADDITIONALHOSTS`; in Docker this is mandatory. For UDP-hostile networks set `webrtcLocalTCPAddress: :8189` (and open TCP 8189) or use TURN. |
| Black video, but `WEBRTC` shown | Usually a missing SPS/PPS or profile problem. The encoder sends SPS/PPS before every IDR (`dump_extra`) with a 1 s GOP, so it should recover within 1 s. Check `chrome://webrtc-internals` → `framesDecoded` increasing. |
| Backend 502 "rejected the backend credentials" | `MEDIAMTX_READ_PASS` ≠ `MTX_AUTHINTERNALUSERS_1_PASS`. |
| High latency | Use `STREAM_X264_PRESET=ultrafast` or NVENC if the encoders are CPU-bound (`frames_dropped` grows in the `[STREAM] stopped:` summary). Check the stats overlay's jitter buffer (should be < 100 ms on LAN) and RTT. Wi-Fi viewers: lower `STREAM_BITRATE_KBPS`. |
| Stutter | CPU saturation on the CARLA machine (lower the preset, or use NVENC / a lower resolution), or packet loss (stats `lost`): lower the bitrate. |
| Profile mismatch / no H.264 in the browser | The stream is constrained baseline `42e01f`, which every browser decodes. Firefox on Linux needs the OpenH264 plugin (installed automatically, can take a minute on first use). |
| Simulator paused | The video keeps showing the last frame (keep-alive), so viewers don't disconnect. After a CARLA restart the encoders continue; a restarted encoder takes over the path (`overridePublisher`). |
