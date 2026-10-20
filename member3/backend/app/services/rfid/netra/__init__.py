"""NETRA: RFID tag <-> camera track association with certified confirmation.

core.py      the algorithm (from ``claude try/netra.py``)
geometry.py  junction camera box + depth -> ground plane
adapter.py   v2 reports / camera_frame boxes -> NETRA reads / tracks
shadow.py    one assessment per sighting, used by the service in shadow mode
"""

from app.services.rfid.netra.shadow import NetraShadow  # noqa: F401
