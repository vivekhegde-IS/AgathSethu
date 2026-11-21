"""
AGHAT SETHU — Application Configuration
Loads all settings from environment variables / .env file.
"""

from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+psycopg://postgres:password@localhost:5432/Aghat_Sethu"

    @field_validator("DATABASE_URL")
    @classmethod
    def _use_psycopg3(cls, url: str) -> str:
        # Hosts (Render, Neon) hand out postgres:// or postgresql:// URLs;
        # SQLAlchemy would pick psycopg2 for those, which is not installed.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    # JWT
    JWT_SECRET: str = "CHANGE_ME_GENERATE_A_REAL_SECRET"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # CORS (comma-separated list of allowed origins)
    CORS_ORIGINS: str = "http://localhost:5173"

    # App
    APP_ENV: str = "development"
    # Public address of the website, used for links in emails
    SITE_URL: str = "http://localhost:5173"

    # Welcome email on a user's first login (SMTP, e.g. Gmail with an App
    # Password). Empty SMTP_PASSWORD = emails are not sent.
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    MAIL_FROM_NAME: str = "AGHAT SETHU"

    # Where the backend keeps its files (evidence photos, fine snapshots and
    # clips, routine-violation outputs, live-ANPR images, stream recordings).
    # Empty = this backend folder. Point it at e.g. a Google Drive for desktop
    # folder ("G:\\My Drive\\AghatSethuData"); the database stays in PostgreSQL.
    DATA_DIR: str = ""

    # WebRTC camera streams (MediaMTX; see member3/media-server/README-STREAMING.md)
    WEBRTC_ENABLED: bool = True
    MEDIAMTX_WHEP_URL: str = "http://127.0.0.1:8889"   # MediaMTX WebRTC/WHEP listener (loopback)
    MEDIAMTX_READ_USER: str = "website"
    MEDIAMTX_READ_PASS: str = ""
    # junction:path pairs served to the Live page
    WEBRTC_STREAMS: str = "J01:cam1,J02:cam2,J03:cam3"
    # Shared secret the CARLA sender must pass as ?token= on /ws/carla/cameras.
    # Empty = not checked (Member 1's sender does not send one yet).
    CARLA_INGEST_TOKEN: str = ""
    # A camera counts as connected while frames arrived within this many seconds
    CAMERA_STALE_AFTER_S: float = 5.0
    # JSON list of RTCIceServer dicts handed to browsers
    WEBRTC_ICE_SERVERS: str = '[{"urls": ["stun:stun.l.google.com:19302"]}]'

    # Sign in with Google (vehicle owners only; authority accounts never).
    # All three empty = the Google button is hidden, password login unchanged.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    # Must be registered in Google Cloud Console, e.g.
    # http://localhost:8000/api/auth/google/callback
    GOOGLE_REDIRECT_URI: str = ""
    # Optional demo pre-linking: "arjun.rao=someone@gmail.com,priya.patel=x@gmail.com".
    # Matched once on a verified email, then stored as the account's Google `sub`.
    GOOGLE_OWNER_LINKS: str = ""

    # Crash text messages. Default: ConsoleSmsProvider (logged + stored, nothing
    # sent). Twilio is used only when all three are set; placeholder numbers
    # (+9100000...) are never sent to.
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    # One crash notification per vehicle per incident: alerts for the same car
    # (or its partner) within this many seconds belong to the same incident.
    CRASH_NOTIFY_COOLDOWN_S: float = 120.0
    # Two-vehicle crash: after one owner answers "minor" / "false alarm", the
    # other owner has this many seconds to answer too, else the case is flagged
    # "not resolved" for the authority.
    CRASH_PARTNER_ANSWER_WINDOW_S: float = 30.0
    # resolving a crash needs the owners' codes or a super-admin code (services/resolution_codes.py)
    RESOLUTION_OWNER_CODE_TTL_H: float = 24.0
    RESOLUTION_OVERRIDE_TTL_MIN: float = 30.0
    RESOLUTION_MAX_WRONG: int = 5
    RESOLUTION_LOCK_MIN: float = 15.0

    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH) if ENV_PATH.exists() else ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()


def data_dir() -> Path:
    """Root folder for every file the backend writes (see DATA_DIR)."""
    return Path(settings.DATA_DIR).expanduser() if settings.DATA_DIR.strip() else BACKEND_DIR
