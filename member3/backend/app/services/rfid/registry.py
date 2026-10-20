"""Plate normalization and the EPC -> plate vehicle registry.

The registry is how a TAG becomes a PLATE. A real reader knows an EPC and
nothing else, so the plate is always resolved through this table - never taken
from a message. An unknown EPC resolves to ``None`` and is marked
``UNREGISTERED_TAG``; it is never invented.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.plate_validation import clean_plate_text, format_plate

from app.services.rfid.config import SEED_PLATES, UNREGISTERED_TAG

VEHICLE_IDS = tuple("ABCDEFGH")


def normalize_plate(text: str | None) -> str:
    """Uppercase, drop every non-alphanumeric. 'ka 01-at 4521' -> 'KA01AT4521'."""
    return clean_plate_text(text)


def state_code_of(plate_norm: str | None) -> str | None:
    """First two letters of a normalized plate, when they look like a state."""
    if not plate_norm or len(plate_norm) < 2:
        return None
    head = plate_norm[:2]
    return head if head.isalpha() else None


def display_plate(plate_norm: str | None) -> str | None:
    return format_plate(plate_norm) if plate_norm else None


def epc_for(vehicle_id: str) -> str:
    """Member 1's _epc_for: index is the 1-based position of the vehicle in A-H."""
    index = VEHICLE_IDS.index(vehicle_id) + 1
    return f"E2000017221101{index:02X}{(0xA0B0 + index):04X}"


def seed_rows() -> list[dict]:
    """The registry seed, derived from the EPC formula (test data only)."""
    rows = []
    for vehicle_id in VEHICLE_IDS:
        plate_norm = normalize_plate(SEED_PLATES[vehicle_id])
        rows.append({
            "epc": epc_for(vehicle_id),
            "plate_norm": plate_norm,
            "plate_display": display_plate(plate_norm),
            "state_code": state_code_of(plate_norm),
            "sim_vehicle_id": vehicle_id,      # debug only
        })
    return rows


@dataclass
class RegistryEntry:
    epc: str
    plate_norm: str | None
    plate_display: str | None
    state_code: str | None
    sim_vehicle_id: str | None = None
    registered: bool = True

    @property
    def status(self) -> str:
        return "REGISTERED" if self.registered else UNREGISTERED_TAG


class VehicleRegistry:
    """In-memory view of `vehicle_registry`, loadable from the DB."""

    def __init__(self, entries: list[RegistryEntry] | None = None,
                 by_plate: dict[str, RegistryEntry] | None = None):
        self._by_epc: dict[str, RegistryEntry] = {}
        self._by_plate: dict[str, RegistryEntry] = {}
        for entry in entries or []:
            self.add(entry)
        for plate, entry in (by_plate or {}).items():
            self._by_plate.setdefault(plate, entry)

    def add(self, entry: RegistryEntry) -> None:
        self._by_epc[entry.epc] = entry
        if entry.plate_norm:
            self._by_plate[entry.plate_norm] = entry

    @classmethod
    def from_seed(cls) -> "VehicleRegistry":
        return cls([
            RegistryEntry(epc=row["epc"], plate_norm=row["plate_norm"],
                          plate_display=row["plate_display"], state_code=row["state_code"],
                          sim_vehicle_id=row["sim_vehicle_id"], registered=True)
            for row in seed_rows()
        ])

    def __len__(self) -> int:
        return len(self._by_epc)

    def lookup_epc(self, epc: str | None) -> RegistryEntry | None:
        """None for an unknown EPC: the caller must store NULL, never a guess."""
        if not epc:
            return None
        return self._by_epc.get(str(epc).strip().upper())

    def lookup_plate(self, plate_norm: str | None) -> RegistryEntry | None:
        if not plate_norm:
            return None
        return self._by_plate.get(normalize_plate(plate_norm))

    def resolve(self, epc: str | None) -> tuple[RegistryEntry, str | None]:
        """(entry, warning). Always returns a usable entry.

        Unknown EPC -> an unregistered entry with a NULL plate plus a warning
        the caller is expected to log.
        """
        entry = self.lookup_epc(epc)
        if entry is not None:
            return entry, None
        placeholder = RegistryEntry(epc=str(epc or ""), plate_norm=None, plate_display=None,
                                    state_code=None, registered=False)
        warning = (f"unknown EPC {epc!r}: stored as {UNREGISTERED_TAG} with NULL plate")
        return placeholder, warning

    def check_message_plate(self, epc: str | None, message_plate: str | None) -> str | None:
        """Warn when a legacy message's plate disagrees with the registry.

        The registry always wins; the message's plate is never trusted.
        """
        entry = self.lookup_epc(epc)
        if entry is None or not message_plate:
            return None
        claimed = normalize_plate(message_plate)
        if claimed and claimed != entry.plate_norm:
            return (f"legacy plate {claimed} for {epc} disagrees with registry "
                    f"{entry.plate_norm}: registry wins")
        return None


def build_registry_from_db(session) -> VehicleRegistry:
    """Load the registry from Postgres."""
    from app.models.models import VehicleRegistry as VehicleRegistryRow

    rows = session.query(VehicleRegistryRow).all()
    return VehicleRegistry([
        RegistryEntry(epc=row.epc, plate_norm=row.plate_norm, plate_display=row.plate_display,
                      state_code=row.state_code, sim_vehicle_id=row.sim_vehicle_id,
                      registered=row.plate_norm is not None)
        for row in rows
    ])


def seed_registry(session) -> int:
    """Insert/refresh the registry seed. Idempotent."""
    from app.models.models import VehicleRegistry as VehicleRegistryRow

    written = 0
    for row in seed_rows():
        existing = session.get(VehicleRegistryRow, row["epc"])
        if existing is None:
            session.add(VehicleRegistryRow(**row))
        else:
            existing.plate_norm = row["plate_norm"]
            existing.plate_display = row["plate_display"]
            existing.state_code = row["state_code"]
            existing.sim_vehicle_id = row["sim_vehicle_id"]
        written += 1
    session.commit()
    return written
