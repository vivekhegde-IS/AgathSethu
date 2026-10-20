"""RFID -> camera plate cross-verification.

Public surface:

    from app.services.rfid.service import get_service

    service.on_rfid_message(message)   # cheap, called from the WS handler
    service.on_crash_alert(message)    # cheap, called from the WS handler
    service.on_camera_frame(message)   # cheap, called from the WS handler
    service.counters_snapshot()        # stage counters for logging / the API
"""

from app.services.rfid.config import RfidFeatureConfig, DEFAULT_CONFIG  # noqa: F401
from app.services.rfid.normalize import RfidRead, parse_message  # noqa: F401
from app.services.rfid.registry import VehicleRegistry, epc_for, normalize_plate  # noqa: F401
