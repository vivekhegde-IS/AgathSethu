"""
AGHAT SETHU — The simulated CARLA fleet (cars A-H): the ONE place that maps a
CARLA vehicle to its plate, RFID tag and seeded owner.

How a CARLA actor resolves to a vehicle
---------------------------------------
CARLA actor ids change every run, so they are never used. The v1.8 recording
script (vivek_fb_rfid.py) names its cars A-H and puts three stable identifiers
on every crash_alert / vehicle_state message:

  * ``epc``         - RFID tag, from the script's ``_epc_for`` formula (preferred)
  * ``vehicle_id``  - the letter A-H
  * ``plate_number``- the overlay plate

``resolve_letter`` accepts any of them (and a CARLA ``role_name`` of the form
``aghat_vehicle_<letter>`` should a future script set one) and returns the
letter; the DB lookup (``vehicle_for_message``) then turns that letter into
exactly one ``vehicles`` row and so one owner.

This module is pure data + pure functions (no app imports) so config modules
can import it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VEHICLE_LETTERS = tuple("ABCDEFGH")
ROLE_NAME_PREFIX = "aghat_vehicle_"


def epc_for(letter: str) -> str:
    """Member 1's ``_epc_for``: index = 1-based position of the car in A-H."""
    index = VEHICLE_LETTERS.index(letter) + 1
    return f"E2000017221101{index:02X}{(0xA0B0 + index):04X}"


def normalize_plate(text: str | None) -> str:
    """'KA 01 AT 4521' -> 'KA01AT4521' (how plates are stored)."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


@dataclass(frozen=True)
class FleetCar:
    letter: str
    plate: str            # display form, as on the CARLA overlay
    state_code: str
    state_name: str
    role: str             # ego (human driver) | traffic (autopilot)
    owner_username: str
    owner_name: str

    @property
    def plate_norm(self) -> str:
        return normalize_plate(self.plate)

    @property
    def epc(self) -> str:
        return epc_for(self.letter)

    @property
    def carla_role_name(self) -> str:
        return f"{ROLE_NAME_PREFIX}{self.letter}"


FLEET: dict[str, FleetCar] = {car.letter: car for car in (
    FleetCar("A", "KA 01 AT 4521", "KA", "Karnataka", "ego", "arjun.rao", "Arjun Rao"),
    FleetCar("B", "MH 12 BR 7814", "MH", "Maharashtra", "traffic", "siddharth.kulkarni", "Siddharth Kulkarni"),
    FleetCar("C", "TN 09 CK 2365", "TN", "Tamil Nadu", "traffic", "karthik.subramanian", "Karthik Subramanian"),
    FleetCar("D", "KL 07 DL 9182", "KL", "Kerala", "traffic", "anjali.nair", "Anjali Nair"),
    FleetCar("E", "DL 03 EN 6047", "DL", "Delhi", "traffic", "rohit.malhotra", "Rohit Malhotra"),
    FleetCar("F", "GJ 05 FP 3419", "GJ", "Gujarat", "traffic", "priya.patel", "Priya Patel"),
    FleetCar("G", "AP 16 GQ 8273", "AP", "Andhra Pradesh", "traffic", "venkata.reddy", "Venkata Sai Reddy"),
    FleetCar("H", "TG 08 HR 5196", "TG", "Telangana", "traffic", "sravani.goud", "Sravani Goud"),
)}

# letter -> display plate (what rfid/config.py SEED_PLATES used to hard-code)
PLATES = {letter: car.plate for letter, car in FLEET.items()}

_BY_EPC = {car.epc: letter for letter, car in FLEET.items()}
_BY_PLATE = {car.plate_norm: letter for letter, car in FLEET.items()}


def resolve_letter(*, epc: str | None = None, vehicle_id: str | None = None,
                   plate: str | None = None, role_name: str | None = None) -> str | None:
    """The car A-H a pipeline message refers to, or None. EPC wins, then the
    role_name, then the letter, then the plate. Conflicting identifiers (an EPC
    of one car with the letter of another) resolve to None: never guess."""
    candidates = []
    if epc:
        candidates.append(_BY_EPC.get(str(epc).strip().upper()))
    if role_name and str(role_name).startswith(ROLE_NAME_PREFIX):
        candidates.append(str(role_name)[len(ROLE_NAME_PREFIX):].upper() or None)
    if vehicle_id:
        letter = str(vehicle_id).strip().upper()
        candidates.append(letter if letter in FLEET else None)
    if plate:
        candidates.append(_BY_PLATE.get(normalize_plate(plate)))
    found = {c for c in candidates if c}
    if len(found) != 1:
        return None
    letter = found.pop()
    # an identifier that was given but does not resolve to a fleet car is a conflict
    if any(c is None for c in candidates):
        return None
    return letter


def vehicle_for_message(db, message: dict, prefix: str = ""):
    """The ``vehicles`` row (and so the owner) a pipeline message refers to.
    ``prefix`` selects the partner fields (``collision_partner``) when given."""
    from app.models.models import Vehicle

    if prefix == "partner":
        letter = resolve_letter(vehicle_id=message.get("collision_partner"),
                                plate=message.get("collision_partner_plate"))
    else:
        letter = resolve_letter(epc=message.get("epc"), vehicle_id=message.get("vehicle_id"),
                                plate=message.get("plate_number"), role_name=message.get("role_name"))
    if letter is None:
        return None
    return db.query(Vehicle).filter(Vehicle.carla_letter == letter).one_or_none()
