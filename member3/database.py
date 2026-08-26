"""
Member 3: Database Storage Interface Shim.
Re-exports database models, sessions, and repositories from member3.database.
"""

from member3.database import (
    init_db,
    get_db_session,
    get_session_direct,
    EventModel,
    IncidentModel,
    EvidenceModel,
    VehicleHistoryModel,
    EventRepository,
    VehicleHistoryRepository,
    IncidentRepository
)

__all__ = [
    "init_db",
    "get_db_session",
    "get_session_direct",
    "EventModel",
    "IncidentModel",
    "EvidenceModel",
    "VehicleHistoryModel",
    "EventRepository",
    "VehicleHistoryRepository",
    "IncidentRepository"
]
