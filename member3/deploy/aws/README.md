# AGHAT SETHU backend on AWS EC2

Frontend stays on Vercel (`https://agath-sethu.vercel.app`). This runs the
FastAPI backend with the full AI stack (Level 1 routine violations, ANPR) on
one EC2 instance, with PostgreSQL and HTTPS (Caddy) on the same machine.

```
Vercel ──HTTPS──▶ EC2 t3.medium, Ubuntu 24.04
                  ├─ Caddy :443  → https://<ip-with-dashes>.sslip.io
                  ├─ uvicorn :8000 (systemd: aghat-backend)
                  └─ PostgreSQL (aghat_sethu)
```

## 1. Launch the instance (AWS console)
1. Region (top right): **Asia Pacific (Mumbai) ap-south-1**.
2. **EC2 → Launch instance**
   - Name: `aghat-sethu-backend`
   - AMI: **Ubuntu Server 24.04 LTS (64-bit x86)**
   - Instance type: **t3.medium**
   - Key pair: **Create new key pair** → name `aghat-key`, RSA, `.pem` → saves `aghat-key.pem`
   - Network settings → **Edit** → security group `aghat-sethu-sg` with inbound rules:
     - SSH, TCP 22, source **My IP**
     - HTTP, TCP 80, source **Anywhere (0.0.0.0/0)**
     - HTTPS, TCP 443, source **Anywhere (0.0.0.0/0)**
   - Storage: **30 GiB gp3**
   - **Launch instance**
3. **EC2 → Elastic IPs → Allocate Elastic IP address → Allocate**, then
   **Actions → Associate Elastic IP address** → the instance → **Associate**.
   (A fixed IP keeps the backend URL the same across stop/start.)
4. **Billing → Budgets → Create budget** → monthly cost budget, e.g. $15, with an email alert.

## 2. Upload the model weights (from this PC)
The `.pt` / OpenVINO `.bin` weights are not in git (~56 MB):
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
It prints the backend URL and the three Vercel variables at the end.

## 4. Point Vercel at it
Vercel → project → **Settings → Environment Variables**, edit:
```
VITE_API_BASE_URL=https://<ip-with-dashes>.sslip.io/api
VITE_WS_URL=wss://<ip-with-dashes>.sslip.io/ws
VITE_LIVE_CAMERA_WS_URL=wss://<ip-with-dashes>.sslip.io/ws/live-cameras
```
then **Deployments → ⋯ → Redeploy** (env changes need a rebuild).

## Day to day
- **Update to the latest code:** `sudo bash setup_server.sh` again (it pulls, migrates, restarts).
- **Logs:** `journalctl -u aghat-backend -f`
- **Restart:** `sudo systemctl restart aghat-backend`
- **Save money:** EC2 → Instances → **Stop instance** when not demoing (not *Terminate*,
  which deletes it). Start it again later; everything comes back by itself.
- Uploaded videos/evidence: `/var/lib/aghat-data`. Secrets: `member3/backend/.env` (mode 600).
