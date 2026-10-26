#!/usr/bin/env bash
# Sets up (or updates) the AGHAT SETHU backend on an Ubuntu 24.04 EC2 instance:
# PostgreSQL, the FastAPI backend with the full AI stack (CPU), a systemd
# service and Caddy for HTTPS. Safe to re-run: a re-run pulls the latest code,
# reinstalls dependencies, migrates the database and restarts the backend.
#
#   sudo SEED_AUTHORITY_PASSWORD='...' SEED_CITIZEN_PASSWORD='...' \
#        bash setup_server.sh
#
# Optional: CORS_ORIGINS (default https://agath-sethu.vercel.app),
#           DOMAIN (default <public-ip-with-dashes>.sslip.io).
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
CORS_ORIGINS="${CORS_ORIGINS:-https://agath-sethu.vercel.app}"

step() { echo; echo "== $*"; }
fail() { echo "SETUP FAILED: $*" >&2; exit 1; }
as_app() { sudo -u "$APP_USER" -H "$@"; }

[ "$(id -u)" = 0 ] || fail "run with sudo"
cd /tmp

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
apt-get install -y software-properties-common curl git gnupg openssl postgresql libgl1 \
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
CORS_ORIGINS=$CORS_ORIGINS
APP_ENV=production
DATA_DIR=$DATA_DIR
WEBRTC_ENABLED=false
ENV
    echo "wrote $ENV_FILE"
else
    sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=$CORS_ORIGINS|" "$ENV_FILE"
    echo "kept $ENV_FILE (CORS_ORIGINS=$CORS_ORIGINS)"
fi
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

# 7) Backend service ------------------------------------------------------------------
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

# 8) HTTPS ----------------------------------------------------------------------------
if [ -z "${DOMAIN:-}" ]; then
    PUBLIC_IP=$(curl -fsS https://checkip.amazonaws.com)
    DOMAIN="${PUBLIC_IP//./-}.sslip.io"
fi
step "Caddy (HTTPS for $DOMAIN)"
cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
CADDY
systemctl enable caddy
systemctl reload caddy || systemctl restart caddy

# 9) Check ----------------------------------------------------------------------------
step "Waiting for the backend"
for _ in $(seq 1 60); do
    curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
    sleep 2
done
curl -fsS http://127.0.0.1:8000/api/health || fail "backend not answering: journalctl -u aghat-backend -n 100"
echo
echo
echo "Backend is up:  https://$DOMAIN/api/health"
echo "Vercel env:     VITE_API_BASE_URL=https://$DOMAIN/api"
echo "                VITE_WS_URL=wss://$DOMAIN/ws"
echo "                VITE_LIVE_CAMERA_WS_URL=wss://$DOMAIN/ws/live-cameras"
