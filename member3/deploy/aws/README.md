# AGHAT SETHU on AWS EC2

Frontend stays on Vercel (`https://agath-sethu.vercel.app`). One EC2 instance
runs everything else: the FastAPI backend with the full AI stack (Level 1
routine violations, ANPR, RFID cross-verification), PostgreSQL, MediaMTX for
the live H.264/WebRTC camera streams, and Caddy for HTTPS.

```
CARLA PC ── RTSP/TCP 8554 (H.264) ───────────────▶ ┌ EC2 (Elastic IP) ───────────────────┐
         ── WSS 443 /ws/carla/cameras (JPEG) ────▶ │ Caddy :443 → <ip-dashes>.sslip.io   │
                                                   │ uvicorn :8000  (aghat-backend)      │
Vercel site ── HTTPS 443 /api, WSS /ws ─────────▶  │ MediaMTX :8554 / :8189 (aghat-mediamtx)
Browser ◀══ WebRTC media UDP/TCP 8189 ═══════════  │ PostgreSQL                          │
                                                   └─────────────────────────────────────┘
```

## 1. Launch the instance (AWS console)
1. Region (top right): **Asia Pacific (Mumbai) ap-south-1**.
2. **EC2 → Launch instance**
   - Name: `aghat-sethu-backend`
   - AMI: **Ubuntu Server 24.04 LTS**, architecture **64-bit (x86)**
   - Instance type: **m7i-flex.large** (2 vCPU, 8 GB); `t3.medium` (4 GB) also works
   - Key pair: **Create new key pair** → `aghat-key`, RSA, `.pem`
   - Network settings → **Edit** → **Create security group** `aghat-sethu-sg`, inbound rules:

     | Type | Protocol | Port | Source | For |
     |---|---|---|---|---|
     | SSH | TCP | 22 | My IP | admin |
     | HTTP | TCP | 80 | Anywhere | HTTPS certificate |
     | HTTPS | TCP | 443 | Anywhere | website API + WebSockets |
     | Custom TCP | TCP | 8554 | Anywhere | CARLA → MediaMTX (password protected) |
     | Custom UDP | UDP | 8189 | Anywhere | WebRTC video to browsers |
     | Custom TCP | TCP | 8189 | Anywhere | WebRTC fallback when UDP is blocked |
   - Storage: **30 GiB gp3** → **Launch instance**
3. **EC2 → Elastic IPs → Allocate** → **Actions → Associate** with the instance.
4. **Billing → Budgets → Create budget** → monthly cost budget with an email alert.

## 2. Upload the model weights (from this PC)
```powershell
cd member3
tar -czf $env:TEMP\aghat-models.tar.gz --exclude=openvino_cache backend/models HelmetAI/models
scp -i aghat-key.pem $env:TEMP\aghat-models.tar.gz ubuntu@<ELASTIC_IP>:/tmp/
```

## 3. Run the setup on the server
```bash
ssh -i aghat-key.pem ubuntu@<ELASTIC_IP>
curl -fsSLO https://raw.githubusercontent.com/vivekhegde-IS/AgathSethu/main/member3/deploy/aws/setup_server.sh
sudo SEED_AUTHORITY_PASSWORD='...' SEED_CITIZEN_PASSWORD='...' bash setup_server.sh
```
At the end it prints (and saves to `/root/aghat-credentials.txt`) the Vercel
variables and the CARLA PC settings.

## 4. Point Vercel at it
Vercel → project → **Settings → Environment Variables**: set the four printed
`VITE_*` values, then **Deployments → ⋯ → Redeploy**.

## 5. Stream from the CARLA PC
In the PowerShell that runs the simulation, set the four printed variables, then
`python full_run.py`. Look for `[STREAM camN] encoding 1280x720@30`; the Live
page tiles then show `WEBRTC`.

Upload needed on the CARLA PC: about 9 Mbps (3 × H.264 at 3 Mbps) + ~13 Mbps
(JPEG feed). Lower `STREAM_BITRATE_KBPS` if the connection is slower.

## Day to day
- **Update to the latest code:** `sudo bash setup_server.sh` again (pulls, migrates, restarts; secrets kept).
- **Logs:** `journalctl -u aghat-backend -f`, `journalctl -u aghat-mediamtx -f`
- **Restart:** `sudo systemctl restart aghat-backend aghat-mediamtx`
- **Save money:** EC2 → Instances → **Stop instance** when not demoing (not *Terminate*).
  Start it again later; everything starts by itself, same IP and URL.
- Uploaded videos/evidence: `/var/lib/aghat-data`. Secrets: `member3/backend/.env`,
  `/etc/aghat/mediamtx.env`, `/root/aghat-credentials.txt` (all mode 600).
