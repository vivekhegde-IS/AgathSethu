"""
AGHAT SETHU — Application Configuration
Loads all settings from environment variables / .env file.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+psycopg://postgres:password@localhost:5432/Aghat_Sethu"

    # JWT
    JWT_SECRET: str = "CHANGE_ME_GENERATE_A_REAL_SECRET"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # CORS (comma-separated list of allowed origins)
    CORS_ORIGINS: str = "http://localhost:5173"

    # App
    APP_ENV: str = "development"

    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH) if ENV_PATH.exists() else ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
