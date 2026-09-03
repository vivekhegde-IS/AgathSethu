"""
AGHAT SETHU — Development Seed Script
======================================
Creates realistic development/demo data for testing.

⚠️  DEVELOPMENT / DEMO ONLY — DO NOT USE IN PRODUCTION ⚠️
All credentials here are placeholder values for local development.

Usage:
    cd backend
    python seed.py

Prerequisites:
    - PostgreSQL running with aghat_sethu database created
    - .env file configured with DATABASE_URL
    - alembic upgrade head already run
"""

import sys
import uuid
from datetime import datetime, timedelta, timezone

# Ensure utf-8 output for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure backend/ is on path
sys.path.insert(0, ".")

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.models import (
    ANPRDetection,
    Camera,
    Challan,
    CollisionEvent,
    Evidence,
    Incident,
    Junction,
    Payment,
    RFIDRead,
    User,
    Vehicle,
    Violation,
)

# ── Seed Credentials (DEVELOPMENT ONLY) ─────────────────────────────────────────
# ⚠️  Change these before any real deployment ⚠️
SEED_AUTHORITY_EMAIL = "inspector.vikram@trafficops.blr.gov.in"
SEED_AUTHORITY_PASSWORD = "Authority@Dev2026"   # dev only

SEED_CITIZEN_EMAIL = "aarav.sharma@example.com"
SEED_CITIZEN_PASSWORD = "Citizen@Dev2026"       # dev only


def utcnow():
    return datetime.now(timezone.utc)


def seed_db():
    db = SessionLocal()
    try:
        print("\n🌱 AGHAT SETHU — Seeding development database...")
        print("⚠️  DEVELOPMENT DATA ONLY — DO NOT USE IN PRODUCTION\n")

        # ── Users ─────────────────────────────────────────────────────────────────
        print("📋 Creating users...")

        # Clear existing seed users
        db.query(User).filter(User.email.in_([SEED_AUTHORITY_EMAIL, SEED_CITIZEN_EMAIL])).delete()
        db.commit()

        authority_user = User(
            id=uuid.uuid4(),
            email=SEED_AUTHORITY_EMAIL,
            password_hash=hash_password(SEED_AUTHORITY_PASSWORD),
            full_name="Inspector Vikram Sen",
            role="authority",
            status="active",
            badge_number="KA-TP-8841",
            jurisdiction="Bangalore East Traffic Division",
            phone="+91 98450 12345",
        )
        db.add(authority_user)

        citizen_user = User(
            id=uuid.uuid4(),
            email=SEED_CITIZEN_EMAIL,
            password_hash=hash_password(SEED_CITIZEN_PASSWORD),
            full_name="Aarav Sharma",
            role="citizen",
            status="active",
            phone="+91 98765 43210",
        )
        db.add(citizen_user)
        db.commit()
        db.refresh(authority_user)
        db.refresh(citizen_user)
        print(f"  ✅ Authority: {authority_user.email} (status=active)")
        print(f"  ✅ Citizen:   {citizen_user.email} (status=active)")

        # ── Junctions ─────────────────────────────────────────────────────────────
        print("\n🚦 Creating junctions...")
        junctions = [
            Junction(id=uuid.uuid4(), name="Silk Board Junction", location_description="Outer Ring Road & Hosur Road, Bangalore", latitude=12.9170, longitude=77.6228, status="active"),
            Junction(id=uuid.uuid4(), name="Hebbal Flyover Junction", location_description="NH 44 & Bellary Road, Bangalore", latitude=13.0358, longitude=77.5972, status="active"),
            Junction(id=uuid.uuid4(), name="Marathahalli Bridge", location_description="HAL Old Airport Road, Marathahalli, Bangalore", latitude=12.9560, longitude=77.7010, status="active"),
        ]
        db.add_all(junctions)
        db.commit()
        print(f"  ✅ {len(junctions)} junctions created")

        # ── Cameras ───────────────────────────────────────────────────────────────
        print("\n📸 Creating cameras...")
        cameras = [
            Camera(id=uuid.uuid4(), junction_id=junctions[0].id, name="SBJ-CAM-01-ANPR", camera_type="anpr", direction="North", status="active"),
            Camera(id=uuid.uuid4(), junction_id=junctions[0].id, name="SBJ-CAM-02-SPEED", camera_type="speed", direction="South", status="active"),
            Camera(id=uuid.uuid4(), junction_id=junctions[1].id, name="HEB-CAM-01-ANPR", camera_type="anpr", direction="East", status="active"),
            Camera(id=uuid.uuid4(), junction_id=junctions[2].id, name="MAR-CAM-01-TRAFFIC", camera_type="traffic", direction="West", status="fault"),
        ]
        db.add_all(cameras)
        db.commit()
        print(f"  ✅ {len(cameras)} cameras created")

        # ── Vehicles ──────────────────────────────────────────────────────────────
        print("\n🚗 Creating vehicles...")
        vehicles = [
            Vehicle(id=uuid.uuid4(), owner_id=citizen_user.id, plate_number="KA01MJ4582", make="Maruti Suzuki", model="Swift", year=2021, color="White", vehicle_type="Car", fastag_id="FTAG-KA01MJ4582-001"),
            Vehicle(id=uuid.uuid4(), owner_id=citizen_user.id, plate_number="KA05MG7291", make="Honda", model="Activa", year=2022, color="Black", vehicle_type="Two-Wheeler"),
            Vehicle(id=uuid.uuid4(), owner_id=citizen_user.id, plate_number="KA19NC3401", make="Toyota", model="Innova Crysta", year=2020, color="Silver", vehicle_type="SUV", fastag_id="FTAG-KA19NC3401-003"),
        ]
        db.add_all(vehicles)
        db.commit()
        print(f"  ✅ {len(vehicles)} vehicles created")

        # ── Violations ────────────────────────────────────────────────────────────
        print("\n⚠️  Creating violations...")
        violations = [
            Violation(
                id=uuid.uuid4(), vehicle_id=vehicles[0].id, camera_id=cameras[1].id,
                violation_type="Speeding", severity="high", fine_amount=2000.0,
                speed_recorded=89.5, speed_limit=60.0,
                location_description="Silk Board Junction, ORR Southbound",
                status="issued",
                created_at=utcnow() - timedelta(days=5),
            ),
            Violation(
                id=uuid.uuid4(), vehicle_id=vehicles[0].id, camera_id=cameras[0].id,
                violation_type="Signal Violation", severity="medium", fine_amount=1000.0,
                location_description="Silk Board Junction, Hosur Road approach",
                status="pending",
                created_at=utcnow() - timedelta(days=2),
            ),
            Violation(
                id=uuid.uuid4(), vehicle_id=vehicles[2].id, camera_id=cameras[2].id,
                violation_type="Speeding", severity="medium", fine_amount=1500.0,
                speed_recorded=72.3, speed_limit=60.0,
                status="paid",
                created_at=utcnow() - timedelta(days=15),
            ),
        ]
        db.add_all(violations)
        db.commit()
        print(f"  ✅ {len(violations)} violations created")

        # ── Challans ──────────────────────────────────────────────────────────────
        print("\n📄 Creating challans...")
        challans = [
            Challan(
                id=uuid.uuid4(), violation_id=violations[0].id, vehicle_id=vehicles[0].id,
                challan_number="BLR-CHN-20260897-001", amount=2000.0,
                due_date=utcnow() + timedelta(days=30), status="pending",
            ),
            Challan(
                id=uuid.uuid4(), violation_id=violations[2].id, vehicle_id=vehicles[2].id,
                challan_number="BLR-CHN-20260882-002", amount=1500.0,
                due_date=utcnow() - timedelta(days=5), status="paid",
                paid_at=utcnow() - timedelta(days=7),
            ),
        ]
        db.add_all(challans)
        db.commit()
        print(f"  ✅ {len(challans)} challans created")

        # ── Incident ──────────────────────────────────────────────────────────────
        print("\n🚨 Creating sample incident...")
        incident = Incident(
            id=uuid.uuid4(),
            junction_id=junctions[0].id,
            incident_type="Collision",
            severity="high",
            status="under_investigation",
            description="Multi-vehicle rear-end collision at Silk Board Junction Southbound. CARLA detected anomalous deceleration patterns.",
            latitude=12.9170,
            longitude=77.6228,
            created_at=utcnow() - timedelta(hours=3),
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)

        # ── Collision Event ────────────────────────────────────────────────────────
        collision = CollisionEvent(
            id=uuid.uuid4(),
            incident_id=incident.id,
            vehicle_ids=[str(vehicles[0].id), str(vehicles[2].id)],
            severity="high",
            collision_type="Rear-end",
            description="Vehicle KA01MJ4582 rear-ended KA19NC3401. Speed differential: ~35 km/h.",
            kalman_confidence=0.94,
            timestamp=utcnow() - timedelta(hours=3),
        )
        db.add(collision)

        # ── ANPR Detections ────────────────────────────────────────────────────────
        print("\n🔍 Creating ANPR detections...")
        anpr_detections = [
            ANPRDetection(
                id=uuid.uuid4(), vehicle_id=vehicles[0].id, camera_id=cameras[0].id,
                incident_id=incident.id, plate_text="KA01MJ4582",
                confidence=0.97, timestamp=utcnow() - timedelta(hours=3, minutes=2),
            ),
            ANPRDetection(
                id=uuid.uuid4(), vehicle_id=vehicles[2].id, camera_id=cameras[0].id,
                incident_id=incident.id, plate_text="KA19NC3401",
                confidence=0.95, timestamp=utcnow() - timedelta(hours=3, minutes=2),
            ),
            ANPRDetection(
                id=uuid.uuid4(), vehicle_id=vehicles[0].id, camera_id=cameras[1].id,
                plate_text="KA01MJ4582", confidence=0.98,
                timestamp=utcnow() - timedelta(days=5, hours=1),
            ),
        ]
        db.add_all(anpr_detections)

        # ── RFID Reads ────────────────────────────────────────────────────────────
        print("📡 Creating RFID reads...")
        rfid_reads = [
            RFIDRead(
                id=uuid.uuid4(), vehicle_id=vehicles[0].id, incident_id=incident.id,
                reader_id="RFID-SBJ-N01", tag_id="FTAG-KA01MJ4582-001",
                speed=89.5, lane="1", direction="Southbound",
                fused_position={"lat": 12.9170, "lng": 77.6228},
                timestamp=utcnow() - timedelta(hours=3, minutes=1),
            ),
            RFIDRead(
                id=uuid.uuid4(), vehicle_id=vehicles[2].id, incident_id=incident.id,
                reader_id="RFID-SBJ-N01", tag_id="FTAG-KA19NC3401-003",
                speed=55.2, lane="1", direction="Southbound",
                fused_position={"lat": 12.9172, "lng": 77.6228},
                timestamp=utcnow() - timedelta(hours=3, minutes=1),
            ),
        ]
        db.add_all(rfid_reads)

        # ── Evidence ──────────────────────────────────────────────────────────────
        print("📁 Creating evidence records...")
        evidence = [
            Evidence(
                id=uuid.uuid4(), incident_id=incident.id,
                evidence_type="anpr_frame",
                url="https://storage.aghat-sethu.dev/evidence/INC-001/anpr-frame-001.jpg",
                description="ANPR capture of KA01MJ4582 at Silk Board, 3 seconds before collision",
                captured_at=utcnow() - timedelta(hours=3, minutes=2),
            ),
            Evidence(
                id=uuid.uuid4(), incident_id=incident.id,
                evidence_type="video",
                url="https://storage.aghat-sethu.dev/evidence/INC-001/cam01-segment.mp4",
                description="Traffic camera recording — 2 minute window around collision",
                captured_at=utcnow() - timedelta(hours=3),
            ),
        ]
        db.add_all(evidence)
        db.commit()

        print(f"\n{'='*60}")
        print("✅ Seed complete!")
        print(f"{'='*60}")
        print("\n⚠️  DEVELOPMENT CREDENTIALS (NEVER USE IN PRODUCTION):")
        print(f"\n  Authority login:")
        print(f"    Email:    {SEED_AUTHORITY_EMAIL}")
        print(f"    Password: {SEED_AUTHORITY_PASSWORD}")
        print(f"\n  Citizen login:")
        print(f"    Email:    {SEED_CITIZEN_EMAIL}")
        print(f"    Password: {SEED_CITIZEN_PASSWORD}")
        print(f"\n{'='*60}\n")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_db()
