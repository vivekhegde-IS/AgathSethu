"""
AGHAT SETHU — SQLAlchemy Database Engine and Session Factory
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# ── Engine ───────────────────────────────────────────────────────────────────────
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,          # detect stale connections
    pool_size=10,
    max_overflow=20,
    echo=(settings.APP_ENV == "development"),
)

# ── Session factory ───────────────────────────────────────────────────────────────
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Base class for ORM models ─────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
