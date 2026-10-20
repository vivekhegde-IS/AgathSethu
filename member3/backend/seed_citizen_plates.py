"""
AGHAT SETHU — Seed citizen accounts for the plates seen in the videos

    python seed_citizen_plates.py all               # every step below, in order
    python seed_citizen_plates.py register-videos   # videos table <- video folders
    python seed_citizen_plates.py build-seed        # data/citizen_seed.csv <- plates read in past runs
    python seed_citizen_plates.py seed-citizens     # users + vehicles <- seed csv; writes credentials csv
    python seed_citizen_plates.py verify-logins     # logs every credential in via POST /api/auth/login

Run `alembic upgrade head` first (migration 005 creates videos / fines).

Accounts are ordinary citizen rows in the existing `users` table (role
citizen, status active, password hashed with app.core.security.hash_password,
the same bcrypt the citizen login verifies) and each plate is a row in the
existing `vehicles` table owned by that user. They log in at /citizen/login
with email <plate>@example.com.

The seed file is plain CSV (number_plate,full_name,phone): edit it and re-run
seed-citizens. build-seed only ADDS plates it has not seen. A plate already in
`vehicles` (owned by someone else) is left alone. Plaintext passwords exist
only in data/citizen_credentials.csv, written when an account is created (or
with --reset-passwords): a bcrypt hash cannot be turned back into a password.
"""

import argparse
import csv
import json
import logging
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core import database  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.citizen_fines import Video  # noqa: E402
from app.models.models import User, Vehicle  # noqa: E402
from app.services.fine_service import VIDEO_DIRS, VIDEO_EXTENSIONS, normalize_plate  # noqa: E402

database.engine.echo = False   # keep the output readable (APP_ENV=development echoes SQL)

BACKEND_DIR = Path(__file__).resolve().parent
DATA_DIR = BACKEND_DIR / "data"
SEED_CSV = DATA_DIR / "citizen_seed.csv"
CREDENTIALS_CSV = DATA_DIR / "citizen_credentials.csv"
RUNS_DIR = BACKEND_DIR / "runtime" / "routine_violations" / "outputs"
SEED_FIELDS = ["number_plate", "full_name", "phone"]
CREDENTIAL_FIELDS = ["email", "password", "number_plate", "full_name"]
EMAIL_DOMAIN = "example.com"            # same reserved test domain as the existing demo citizens
PASSWORD_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"   # no 0/O, 1/l/I


def _password(default):
    return default or "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(10))


def _read_csv(path):
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def register_videos(dirs):
    db = database.SessionLocal()
    try:
        known = {v.path for v in db.query(Video).all()}
        added = 0
        for folder in dirs:
            if not folder.is_dir():
                print(f"  skip (missing): {folder}")
                continue
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() in VIDEO_EXTENSIONS and str(path) not in known:
                    db.add(Video(filename=path.name, path=str(path)))
                    known.add(str(path))
                    added += 1
                    print(f"  + {path.name}  ({folder})")
        db.commit()
        print(f"register-videos: {added} new, {len(known)} total")
    finally:
        db.close()


def build_seed():
    """Collect every valid plate the routine pipeline has read in past runs."""
    rows = _read_csv(SEED_CSV)
    have = {normalize_plate(r["number_plate"]) for r in rows}
    found = {}
    for summary_path in sorted(RUNS_DIR.glob("*/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for vehicle in summary.get("vehicles") or []:
            plate = normalize_plate(vehicle.get("plate_compact"))   # empty unless the plate validated
            if plate:
                found.setdefault(plate, summary.get("video"))
    added = 0
    for plate, video in sorted(found.items()):
        if plate not in have:
            rows.append({"number_plate": plate, "full_name": f"Citizen {plate}", "phone": ""})
            have.add(plate)
            added += 1
            print(f"  + {plate}  (seen in {video})")
    _write_csv(SEED_CSV, SEED_FIELDS, rows)
    print(f"build-seed: {added} new plate(s), {len(rows)} in {SEED_CSV}")


def seed_citizens(seed_path, reset_passwords, default_password):
    rows = _read_csv(seed_path)
    if not rows:
        print(f"seed-citizens: no rows in {seed_path} (run build-seed or fill it in)")
        return
    credentials = {r["email"]: r for r in _read_csv(CREDENTIALS_CSV)}
    db = database.SessionLocal()
    try:
        created = written = skipped = 0
        for row in rows:
            plate = normalize_plate(row.get("number_plate"))
            if not plate:
                continue
            email = f"{plate.lower()}@{EMAIL_DOMAIN}"
            name = (row.get("full_name") or "").strip() or f"Citizen {plate}"
            vehicle = db.query(Vehicle).filter(Vehicle.plate_number == plate).first()
            user = db.query(User).filter(User.email == email).first()
            if vehicle is not None and (user is None or vehicle.owner_id != user.id):
                print(f"  skip {plate}: already registered to another account")
                skipped += 1
                continue
            new_password = None
            if user is None:
                new_password = _password(default_password)
                user = User(email=email, password_hash=hash_password(new_password), full_name=name,
                            role="citizen", status="active", phone=row.get("phone") or None)
                db.add(user)
                db.flush()
                created += 1
            elif reset_passwords:
                new_password = _password(default_password)
                user.password_hash = hash_password(new_password)
            user.full_name = name
            user.phone = row.get("phone") or user.phone
            if vehicle is None:
                db.add(Vehicle(owner_id=user.id, plate_number=plate, vehicle_type="two_wheeler",
                               registered_state=plate[:2], is_active=True))
            if new_password:
                credentials[email] = {"email": email, "password": new_password,
                                      "number_plate": plate, "full_name": name}
                written += 1
            elif email in credentials:
                credentials[email]["full_name"] = name
        db.commit()
        _write_csv(CREDENTIALS_CSV, CREDENTIAL_FIELDS, sorted(credentials.values(), key=lambda r: r["email"]))
        print(f"seed-citizens: {created} account(s) created, {skipped} skipped, "
              f"{written} password(s) written to {CREDENTIALS_CSV}")
    finally:
        db.close()


def verify_logins():
    """Log every credential in through the real citizen login endpoint."""
    from fastapi.testclient import TestClient

    from app.main import app

    logging.getLogger("uvicorn.access").disabled = True
    client = TestClient(app)        # no `with`: the model warm-up lifespan is not started
    rows = _read_csv(CREDENTIALS_CSV)
    failed = 0
    for row in rows:
        response = client.post("/api/auth/login", json={"email": row["email"], "password": row["password"]})
        ok = response.status_code == 200 and response.json()["user"]["role"] == "citizen"
        failed += not ok
        print(f"  {'OK  ' if ok else 'FAIL'} {row['email']:<28} {response.status_code}")
    print(f"verify-logins: {len(rows) - failed}/{len(rows)} logged in via POST /api/auth/login")
    return failed == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["all", "register-videos", "build-seed", "seed-citizens", "verify-logins"])
    parser.add_argument("--dir", action="append", type=Path,
                        help="video folder to register (repeatable; default: media/videos and the repo root)")
    parser.add_argument("--seed", type=Path, default=SEED_CSV, help="citizen seed CSV")
    parser.add_argument("--reset-passwords", action="store_true",
                        help="issue new passwords for seeded accounts that already exist")
    parser.add_argument("--default-password", help="use this password instead of random ones (testing)")
    args = parser.parse_args()

    if args.command in ("all", "register-videos"):
        register_videos(args.dir or VIDEO_DIRS)
    if args.command in ("all", "build-seed"):
        build_seed()
    if args.command in ("all", "seed-citizens"):
        seed_citizens(args.seed, args.reset_passwords, args.default_password)
    if args.command in ("all", "verify-logins"):
        sys.exit(0 if verify_logins() else 1)


if __name__ == "__main__":
    main()
