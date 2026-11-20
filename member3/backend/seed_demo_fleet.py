"""
Seed the CARLA demo fleet: 8 vehicle owners (cars A-H) + 1 authority account.

Idempotent: users are matched on username, vehicles on plate, registry rows on
EPC; running it again updates in place and never creates duplicates.

Passwords are read from the gitignored demo_credentials.local.md (repo root)
and stored only as bcrypt hashes. An existing hash that already matches is
kept unchanged.

    cd member3/backend
    python seed_demo_fleet.py                    # uses ../../demo_credentials.local.md
    python seed_demo_fleet.py --credentials path/to/demo_credentials.local.md
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.database import SessionLocal  # noqa: E402
from app.core.fleet import FLEET  # noqa: E402
from app.core.security import hash_password, verify_password  # noqa: E402
from app.models import citizen_fines  # noqa: E402,F401  (registers fines/notifications)
from app.models.models import User, Vehicle, VehicleRegistry  # noqa: E402
from app.services.plate_validation import format_plate  # noqa: E402

DEFAULT_CREDENTIALS = Path(__file__).resolve().parents[2] / "demo_credentials.local.md"
AUTHORITY = {"username": "authority.admin", "full_name": "Traffic Control Room",
             "email": "control.room@example.com", "badge_number": "TCR-DEMO-01",
             "jurisdiction": "Town10HD (CARLA simulation)", "phone": "+910000000099"}


def placeholder_phone(index: int) -> str:
    """Never a real number: +91 00000 000NN (and sms.py refuses this prefix)."""
    return f"+9100000000{index:02d}"


def read_credentials(path: Path) -> dict[str, str]:
    if not path.exists():
        sys.exit(f"Credentials file not found: {path}\n"
                 "Create demo_credentials.local.md (see README, 'Demo accounts').")
    creds = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and re.fullmatch(r"[a-z]+\.[a-z]+", cells[-2] or ""):
            creds[cells[-2]] = cells[-1]
    return creds


def upsert_user(db, *, username, password, full_name, email, role, phone, **extra) -> tuple[User, bool]:
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None:
        user = db.query(User).filter(User.email == email).one_or_none()
    created = user is None
    if created:
        user = User(email=email, password_hash=hash_password(password), full_name=full_name, role=role,
                    status="active", welcome_email_sent_at=datetime.now(timezone.utc))
        db.add(user)
    elif not verify_password(password, user.password_hash):
        user.password_hash = hash_password(password)
    user.username, user.full_name, user.role, user.status = username, full_name, role, "active"
    user.phone = phone
    if user.welcome_email_sent_at is None:      # example.com addresses: never email them
        user.welcome_email_sent_at = datetime.now(timezone.utc)
    for key, value in extra.items():
        setattr(user, key, value)
    db.flush()
    return user, created


def seed(credentials_path: Path) -> dict:
    creds = read_credentials(credentials_path)
    missing = [c.owner_username for c in FLEET.values() if c.owner_username not in creds]
    missing += [] if AUTHORITY["username"] in creds else [AUTHORITY["username"]]
    if missing:
        sys.exit(f"No password for {missing} in {credentials_path}")

    counts = {"users_created": 0, "users_updated": 0, "vehicles_created": 0, "vehicles_updated": 0}
    db = SessionLocal()
    try:
        for index, car in enumerate(FLEET.values(), start=1):
            owner, created = upsert_user(db, username=car.owner_username, password=creds[car.owner_username],
                                         full_name=car.owner_name, email=f"{car.owner_username}@example.com",
                                         role="citizen", phone=placeholder_phone(index))
            counts["users_created" if created else "users_updated"] += 1

            vehicle = db.query(Vehicle).filter(Vehicle.plate_number == car.plate_norm).one_or_none()
            if vehicle is None:
                vehicle = db.query(Vehicle).filter(Vehicle.carla_letter == car.letter).one_or_none()
            counts["vehicles_created" if vehicle is None else "vehicles_updated"] += 1
            if vehicle is None:
                vehicle = Vehicle(owner_id=owner.id, plate_number=car.plate_norm)
                db.add(vehicle)
            vehicle.owner_id, vehicle.plate_number = owner.id, car.plate_norm
            vehicle.carla_letter, vehicle.carla_role_name = car.letter, car.carla_role_name
            vehicle.rfid_epc, vehicle.fastag_id = car.epc, car.epc
            vehicle.registered_state, vehicle.state_name = car.state_code, car.state_name
            vehicle.vehicle_type = "car"
            vehicle.model = "CARLA ego car (human driver)" if car.role == "ego" else "CARLA traffic (autopilot)"
            vehicle.is_active = True

            row = db.get(VehicleRegistry, car.epc)
            if row is None:
                row = VehicleRegistry(epc=car.epc)
                db.add(row)
            row.plate_norm, row.plate_display = car.plate_norm, format_plate(car.plate_norm) or car.plate
            row.state_code, row.sim_vehicle_id = car.state_code, car.letter

        _, created = upsert_user(db, username=AUTHORITY["username"], password=creds[AUTHORITY["username"]],
                                 full_name=AUTHORITY["full_name"], email=AUTHORITY["email"], role="authority",
                                 phone=AUTHORITY["phone"], badge_number=AUTHORITY["badge_number"],
                                 jurisdiction=AUTHORITY["jurisdiction"])
        counts["users_created" if created else "users_updated"] += 1
        db.commit()
    finally:
        db.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    counts = seed(parser.parse_args().credentials)
    print(f"[SEED] demo fleet: {counts}")


if __name__ == "__main__":
    main()
