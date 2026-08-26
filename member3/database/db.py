"""
Member 3 Database Engine & Session Setup.
Supports PostgreSQL (e.g. postgresql://...) with transparent SQLite fallback.
SQLAlchemy ORM session lifecycle management.
"""

import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from typing import Generator

logger = logging.getLogger("Member3.Database")

Base = declarative_base()
_engine = None
_SessionLocal = None


def init_db(database_url: str = None) -> Session:
    global _engine, _SessionLocal
    if not database_url:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        db_path = os.path.join(root_dir, "member3", "hit_and_run.db")
        database_url = f"sqlite:///{db_path}"

    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}

    logger.info(f"[Member 3 DB] Initializing database connection: {database_url}")
    _engine = create_engine(database_url, connect_args=connect_args, echo=False)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    # Create tables if not exist (safe, won't drop existing tables)
    Base.metadata.create_all(bind=_engine)
    return _SessionLocal()


def get_db_session() -> Generator[Session, None, None]:
    """Dependency helper for FastAPI database sessions."""
    global _SessionLocal
    if _SessionLocal is None:
        init_db()
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_direct() -> Session:
    """Direct session getter for CLI / backend runners."""
    global _SessionLocal
    if _SessionLocal is None:
        return init_db()
    return _SessionLocal()
