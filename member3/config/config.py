"""
Member 3 Configuration Loader.
Loads settings from shared/config/demo_config.yaml merged with Member 3 defaults.
"""

import os
import yaml
from typing import Dict, Any

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def get_demo_config_path() -> str:
    return os.path.join(ROOT_DIR, "shared", "config", "demo_config.yaml")

def load_member3_config() -> Dict[str, Any]:
    cfg_path = get_demo_config_path()
    config: Dict[str, Any] = {
        "project": {
            "name": "AI-Based Hit-and-Run Accident Detection, Vehicle Identification and Multi-Junction Tracking System",
            "mode": "DEMO"
        },
        "system": {
            "api_host": "127.0.0.1",
            "api_port": 8000,
            "database_url": f"sqlite:///{os.path.join(ROOT_DIR, 'member3', 'hit_and_run.db')}"
        },
        "junctions": {
            "J01": {"name": "Junction 1", "description": "North Entry Junction", "is_crash_junction": False},
            "J02": {"name": "Crash Junction", "description": "Main Intersection - Crash Site", "is_crash_junction": True},
            "J03": {"name": "Junction 3", "description": "East Bypass Road - RFID Checkpoint", "is_crash_junction": False},
            "J04": {"name": "Junction 4", "description": "Highway Exit - Camera Checkpoint", "is_crash_junction": False}
        },
        "vehicles": {
            "V001": {"plate_number": "KA01AB1234", "model": "Sedan (Blue)", "role": "VICTIM", "rfid_tag": "TAG_V001_88A"},
            "V002": {"plate_number": "KA05XY5678", "model": "SUV (Black)", "role": "SUSPECT", "rfid_tag": "TAG_V002_99B"}
        },
        "rfid": {
            "reader_id": "RFID_J03_R01",
            "junction_id": "J03",
            "read_range_m": 15.0,
            "cooldown_seconds": 5.0
        }
    }

    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                shared_cfg = yaml.safe_load(f) or {}
                if "project" in shared_cfg:
                    config["project"].update(shared_cfg["project"])
                if "system" in shared_cfg:
                    config["system"].update(shared_cfg["system"])
                if "junctions" in shared_cfg:
                    config["junctions"].update(shared_cfg["junctions"])
                if "vehicles" in shared_cfg:
                    config["vehicles"].update(shared_cfg["vehicles"])
        except Exception as e:
            print(f"[Member 3 Config] Warning loading demo_config.yaml: {e}")

    # Ensure database URL is valid absolute path if relative sqlite
    db_url = config["system"].get("database_url", "")
    if db_url.startswith("sqlite:///") and not os.path.isabs(db_url.replace("sqlite:///", "")):
        rel_path = db_url.replace("sqlite:///", "")
        abs_path = os.path.abspath(os.path.join(ROOT_DIR, rel_path))
        config["system"]["database_url"] = f"sqlite:///{abs_path}"

    return config
