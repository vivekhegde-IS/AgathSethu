#!/usr/bin/env bash
# Sets up (or updates) AGHAT SETHU on an Ubuntu 24.04 EC2 instance: the React
# website, PostgreSQL, the FastAPI backend with the full AI stack (CPU),
# MediaMTX for the live H.264/WebRTC camera streams, systemd services, and
# Caddy serving it all on one HTTPS address (/api and /ws go to the backend).
# Safe to re-run: a re-run pulls the latest code, reinstalls dependencies,
# migrates the database and restarts the services; secrets are kept.
#
#   sudo SEED_AUTHORITY_PASSWORD='...' SEED_CITIZEN_PASSWORD='...' \
#        bash setup_server.sh
#
# Optional: DOMAIN, the site's main name, e.g. aghatsethu.duckdns.org (default:
#           the one saved by the last run, else <public-ip-with-dashes>.sslip.io;
#           the sslip.io name is always served too),
#           CORS_ORIGINS (default both names; add other sites comma-separated).
# Model weights are not in git: copy aghat-models.tar.gz to /tmp first
# (see README.md); it is unpacked into member3/ when present.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/vivekhegde-IS/AgathSethu.git}"
APP_USER=aghat
APP_HOME=/opt/aghat
APP_DIR=$APP_HOME/AgathSethu
BACKEND=$APP_DIR/member3/backend
DATA_DIR=/var/lib/aghat-data
ENV_FILE=$BACKEND/.env
MODELS_TARBALL=/tmp/aghat-models.tar.gz
FRONTEND=$APP_DIR/member3/frontend
WEB_ROOT=/var/www/aghat
MEDIAMTX_VERSION=v1.21.1
MEDIAMTX_SHA256=653abc672a3e693f8d3b2717752492fdcfb8072291ec108d03d3dd857411b0ee
MEDIAMTX_ENV=/etc/aghat/mediamtx.env
SITE_ENV=/etc/aghat/site.env
CREDENTIALS=/root/aghat-credentials.txt

step() { echo; echo "== $*"; }
fail() { echo "SETUP FAILED: $*" >&2; exit 1; }
as_app() { sudo -u "$APP_USER" -H "$@"; }
# Value of KEY in an env file ("" when absent).
env_get() { grep -m1 "^$2=" "$1" 2>/dev/null | cut -d= -f2- || true; }
# Set KEY=VALUE in an env file, replacing an existing line.
env_set() {
    if grep -q "^$2=" "$1"; then sed -i "s|^$2=.*|$2=$3|" "$1"; else echo "$2=$3" >> "$1"; fi
}

[ "$(id -u)" = 0 ] || fail "run with sudo"
cd /tmp
# The Elastic IP: browsers reach MediaMTX's WebRTC media on it, and it gives
# the always-served HTTPS name <ip-with-dashes>.sslip.io.
PUBLIC_IP=$(curl -fsS https://checkip.amazonaws.com)
IP_HOST="${PUBLIC_IP//./-}.sslip.io"
# DOMAIN is the main name (website build, CARLA PC). It is saved, so a re-run
# without DOMAIN keeps a custom name instead of falling back to sslip.io.
mkdir -p /etc/aghat
DOMAIN="${DOMAIN:-$(env_get "$SITE_ENV" DOMAIN)}"
DOMAIN="${DOMAIN:-$IP_HOST}"
echo "DOMAIN=$DOMAIN" > "$SITE_ENV"
SITE_HOSTS="$DOMAIN"
[ "$DOMAIN" = "$IP_HOST" ] || SITE_HOSTS="$DOMAIN, $IP_HOST"
CORS_ORIGINS="${CORS_ORIGINS:-https://${SITE_HOSTS//, /,https://}}"

# 1) Swap: headroom for PyTorch + three detectors on a 4 GB instance ---------------
step "Swap (4 GB)"
if ! swapon --show | grep -q /swapfile; then
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
swapon --show

# 2) System packages ------------------------------------------------------------------
step "System packages (Python 3.11, PostgreSQL, Caddy)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y software-properties-common curl git gnupg openssl rsync postgresql libgl1 \
    debian-keyring debian-archive-keyring apt-transport-https
apt-get install -y libglib2.0-0t64 || apt-get install -y libglib2.0-0
if ! command -v python3.11 >/dev/null; then
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -y
fi
apt-get install -y python3.11 python3.11-venv python3.11-dev
if ! command -v caddy >/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' |
        gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y
    apt-get install -y caddy
fi
if ! node --version 2>/dev/null | grep -q '^v24\.'; then
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key |
        gpg --batch --yes --dearmor -o /usr/share/keyrings/nodesource.gpg
    echo "deb [signed-by=/usr/share/keyrings/nodesource.gpg] https://deb.nodesource.com/node_24.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list
    apt-get update -y
    apt-get install -y nodejs
fi

# 3) Code -----------------------------------------------------------------------------
step "Code ($REPO_URL)"
id "$APP_USER" >/dev/null 2>&1 ||
    useradd --system --create-home --home-dir "$APP_HOME" --shell /usr/sbin/nologin "$APP_USER"
if [ -d "$APP_DIR/.git" ]; then
    as_app git -C "$APP_DIR" pull --ff-only
else
    as_app git clone "$REPO_URL" "$APP_DIR"
fi
as_app git -C "$APP_DIR" log --oneline -1
mkdir -p "$DATA_DIR"
chown "$APP_USER:$APP_USER" "$DATA_DIR"

# 4) Model weights --------------------------------------------------------------------
step "Model weights"
if [ -f "$MODELS_TARBALL" ]; then
    tar -xzf "$MODELS_TARBALL" -C "$APP_DIR/member3"
    chown -R "$APP_USER:$APP_USER" "$APP_DIR/member3/backend/models" "$APP_DIR/member3/HelmetAI"
    echo "unpacked $MODELS_TARBALL"
fi
missing=0
for f in backend/models/vehicle/yolo11n_openvino_model/yolo11n.bin \
         backend/models/helmet/helmet_v4_final_best_openvino_model/helmet_v4_final_best.bin \
         backend/models/number_plate/number_plate_detector_openvino_model/number_plate_detector.bin \
         backend/models/number_plate/number_plate_detector.pt; do
    if [ -f "$APP_DIR/member3/$f" ]; then echo "ok       $f"; else echo "MISSING  $f"; missing=1; fi
done
[ "$missing" = 0 ] || echo "WARNING: Level 1 (routine violations) needs the missing weights."

# 5) Python environment ---------------------------------------------------------------
step "Python packages (CPU PyTorch + AI stack; first run takes ~5-10 min)"
[ -x "$BACKEND/.venv/bin/python" ] || as_app python3.11 -m venv "$BACKEND/.venv"
PIP="$BACKEND/.venv/bin/pip"
as_app "$PIP" install --quiet --upgrade pip
as_app "$PIP" install --quiet torch==2.14.0 torchvision==0.29.0 \
    --index-url https://download.pytorch.org/whl/cpu
as_app "$PIP" install --quiet -r "$BACKEND/requirements-aws.txt"

# 6) Database + .env ------------------------------------------------------------------
step "PostgreSQL database and backend .env"
systemctl enable --now postgresql
if [ ! -f "$ENV_FILE" ]; then
    DB_PASS=$(openssl rand -hex 16)
    sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aghat') THEN
    CREATE ROLE aghat LOGIN PASSWORD '$DB_PASS';
  ELSE
    ALTER ROLE aghat PASSWORD '$DB_PASS';
  END IF;
END \$\$;
SQL
    sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'aghat_sethu'" | grep -q 1 ||
        sudo -u postgres createdb -O aghat aghat_sethu
    cat > "$ENV_FILE" <<ENV
DATABASE_URL=postgresql+psycopg://aghat:$DB_PASS@127.0.0.1:5432/aghat_sethu
JWT_SECRET=$(openssl rand -hex 64)
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
APP_ENV=production
DATA_DIR=$DATA_DIR
ENV
    echo "wrote $ENV_FILE"
else
    echo "kept $ENV_FILE"
fi
# Secrets are generated once and kept across re-runs.
READ_PASS=$(env_get "$ENV_FILE" MEDIAMTX_READ_PASS)
[ -n "$READ_PASS" ] || READ_PASS=$(openssl rand -hex 16)
INGEST_TOKEN=$(env_get "$ENV_FILE" CARLA_INGEST_TOKEN)
[ -n "$INGEST_TOKEN" ] || INGEST_TOKEN=$(openssl rand -hex 24)
env_set "$ENV_FILE" CORS_ORIGINS "$CORS_ORIGINS"
env_set "$ENV_FILE" WEBRTC_ENABLED true
env_set "$ENV_FILE" MEDIAMTX_WHEP_URL http://127.0.0.1:8889
env_set "$ENV_FILE" MEDIAMTX_READ_USER website
env_set "$ENV_FILE" MEDIAMTX_READ_PASS "$READ_PASS"
env_set "$ENV_FILE" CARLA_INGEST_TOKEN "$INGEST_TOKEN"
# Welcome emails: links point at the main name; the sender account is given
# once as SMTP_USER=... and kept. Its password is set separately with
# aghat-set-smtp-password (below), so it is never on a command line.
env_set "$ENV_FILE" SITE_URL "https://$DOMAIN"
[ -z "${SMTP_USER:-}" ] || env_set "$ENV_FILE" SMTP_USER "$SMTP_USER"
cat > /usr/local/sbin/aghat-set-smtp-password <<HELPER
#!/usr/bin/env bash
# Reads the SMTP (Gmail App) password from stdin into the backend .env and
# restarts the backend. Spaces are removed (Google shows it in groups of 4).
set -euo pipefail
IFS= read -r pass
pass="\${pass//[[:space:]]/}"
[ -n "\$pass" ] || { echo "empty password" >&2; exit 1; }
if grep -q '^SMTP_PASSWORD=' "$ENV_FILE"; then
    sed -i "s|^SMTP_PASSWORD=.*|SMTP_PASSWORD=\$pass|" "$ENV_FILE"
else
    echo "SMTP_PASSWORD=\$pass" >> "$ENV_FILE"
fi
systemctl restart aghat-backend
echo "SMTP password saved; backend restarted"
HELPER
chmod 700 /usr/local/sbin/aghat-set-smtp-password
chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"

step "Database schema and demo data"
cd "$BACKEND"
as_app .venv/bin/alembic upgrade head
user_count=$(as_app .venv/bin/python -c "from app.core.database import SessionLocal; from app.models.models import User; print(SessionLocal().query(User).count())")
if [ "$user_count" = 0 ]; then
    [ -n "${SEED_AUTHORITY_PASSWORD:-}" ] && [ -n "${SEED_CITIZEN_PASSWORD:-}" ] ||
        fail "empty database: pass SEED_AUTHORITY_PASSWORD and SEED_CITIZEN_PASSWORD to seed the demo logins"
    as_app env SEED_AUTHORITY_PASSWORD="$SEED_AUTHORITY_PASSWORD" \
        SEED_CITIZEN_PASSWORD="$SEED_CITIZEN_PASSWORD" .venv/bin/python seed_if_empty.py
else
    echo "$user_count users already present - not seeding"
fi
cd /tmp

# 7) MediaMTX: RTSP ingest from the CARLA PC, WebRTC to browsers ----------------------
step "MediaMTX $MEDIAMTX_VERSION (live camera streams)"
if ! /usr/local/bin/mediamtx --version 2>/dev/null | grep -q "$MEDIAMTX_VERSION"; then
    tarball="mediamtx_${MEDIAMTX_VERSION}_linux_amd64.tar.gz"
    curl -fsSLo "/tmp/$tarball" \
        "https://github.com/bluenviron/mediamtx/releases/download/$MEDIAMTX_VERSION/$tarball"
    echo "$MEDIAMTX_SHA256  /tmp/$tarball" | sha256sum -c -
    tar -xzf "/tmp/$tarball" -C /usr/local/bin mediamtx
fi
id mediamtx >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin mediamtx
mkdir -p /etc/aghat
[ -f "$MEDIAMTX_ENV" ] || touch "$MEDIAMTX_ENV"
PUBLISH_PASS=$(env_get "$MEDIAMTX_ENV" MTX_AUTHINTERNALUSERS_0_PASS)
[ -n "$PUBLISH_PASS" ] || PUBLISH_PASS=$(openssl rand -hex 16)
# mediamtx.yml from the repo; secrets and this host's address come from the
# environment (MediaMTX's MTX_* overrides).
env_set "$MEDIAMTX_ENV" MTX_AUTHINTERNALUSERS_0_PASS "$PUBLISH_PASS"
env_set "$MEDIAMTX_ENV" MTX_AUTHINTERNALUSERS_1_PASS "$READ_PASS"
# Behind EC2's 1:1 NAT the interfaces only carry the private address: announce
# the Elastic IP, and accept ICE over TCP 8189 for networks that block UDP.
env_set "$MEDIAMTX_ENV" MTX_WEBRTCADDITIONALHOSTS "$PUBLIC_IP"
env_set "$MEDIAMTX_ENV" MTX_WEBRTCLOCALTCPADDRESS ":8189"
chmod 600 "$MEDIAMTX_ENV"
# The mediamtx user cannot read the app user's home: keep its config in /etc.
install -m 644 "$APP_DIR/member3/media-server/mediamtx.yml" /etc/aghat/mediamtx.yml
cat > /etc/systemd/system/aghat-mediamtx.service <<UNIT
[Unit]
Description=AGHAT SETHU MediaMTX (CARLA camera streams)
After=network-online.target
Wants=network-online.target

[Service]
User=mediamtx
EnvironmentFile=$MEDIAMTX_ENV
ExecStart=/usr/local/bin/mediamtx /etc/aghat/mediamtx.yml
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable aghat-mediamtx
systemctl restart aghat-mediamtx

# 8) Backend service ------------------------------------------------------------------
step "systemd service aghat-backend"
cat > /etc/systemd/system/aghat-backend.service <<UNIT
[Unit]
Description=AGHAT SETHU backend (FastAPI)
After=network-online.target postgresql.service
Wants=network-online.target postgresql.service

[Service]
User=$APP_USER
WorkingDirectory=$BACKEND
Environment=PYTHONUNBUFFERED=1
ExecStart=$BACKEND/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable aghat-backend
systemctl restart aghat-backend

# 9) Website --------------------------------------------------------------------------
step "Website build (React/Vite)"
# .env.production.local is git-ignored, so pulls stay clean.
cat > "$FRONTEND/.env.production.local" <<ENV
VITE_API_BASE_URL=https://$DOMAIN/api
VITE_WS_URL=wss://$DOMAIN/ws
VITE_LIVE_CAMERA_WS_URL=wss://$DOMAIN/ws/live-cameras
VITE_WEBRTC_ENABLED=true
VITE_ENABLE_REAL_AUTH=true
VITE_ENABLE_MOCK_DATA=true
VITE_APP_NAME=AGHAT SETHU
VITE_APP_ENVIRONMENT=production
VITE_JWT_STORAGE_KEY=aghat_sethu_jwt
ENV
chown "$APP_USER:$APP_USER" "$FRONTEND/.env.production.local"
(cd "$FRONTEND" && as_app npm ci --no-audit --no-fund && as_app npm run build)
# Caddy cannot read the app user's home: publish the build to /var/www.
mkdir -p "$WEB_ROOT"
rsync -a --delete "$FRONTEND/dist/" "$WEB_ROOT/"
chmod -R a+rX "$WEB_ROOT"

# 10) HTTPS ---------------------------------------------------------------------------
step "Caddy (HTTPS for $SITE_HOSTS)"
cat > /etc/caddy/Caddyfile <<CADDY
$SITE_HOSTS {
    encode gzip

    # API and WebSockets -> FastAPI
    @backend path /api/* /ws/*
    handle @backend {
        reverse_proxy 127.0.0.1:8000
    }

    # Everything else -> the React app (client-side routes fall back to index.html)
    handle {
        root * $WEB_ROOT
        try_files {path} /index.html
        file_server
    }
}
CADDY
systemctl enable caddy
systemctl reload caddy || systemctl restart caddy

# 11) Check ---------------------------------------------------------------------------
step "Waiting for the backend"
for _ in $(seq 1 60); do
    curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
    sleep 2
done
curl -fsS http://127.0.0.1:8000/api/health || fail "backend not answering: journalctl -u aghat-backend -n 100"
systemctl is-active --quiet aghat-mediamtx || fail "MediaMTX not running: journalctl -u aghat-mediamtx -n 100"

cat > "$CREDENTIALS" <<CREDS
AGHAT SETHU on $DOMAIN ($PUBLIC_IP)

Website:  https://$DOMAIN
Backend:  https://$DOMAIN/api/health

CARLA PC (PowerShell, before python full_run.py):
  \$env:STREAM_RTSP_BASE = "rtsp://$PUBLIC_IP:8554"
  \$env:STREAM_PUBLISH_USER = "carla"
  \$env:STREAM_PUBLISH_PASS = "$PUBLISH_PASS"
  \$env:CARLA_EVIDENCE_WS = "wss://$DOMAIN/ws/carla/cameras?token=$INGEST_TOKEN"
CREDS
chmod 600 "$CREDENTIALS"
echo
cat "$CREDENTIALS"
echo "(saved in $CREDENTIALS)"
