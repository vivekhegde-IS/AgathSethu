"""
Shared Event Validator Utility
Validates event payloads against fixed JSON schemas.
"""
import os
import json
from typing import Tuple, Dict, Any

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schemas")

SCHEMA_MAPPING = {
    "CRASH_DETECTED": "crash_event.json",
    "COLLISION_PAIR_IDENTIFIED": "collision_event.json",
    "ANPR_IDENTIFIED": "anpr_event.json",
    "VEHICLE_OBSERVED": "camera_event.json",
    "RFID_DETECTED": "rfid_event.json",
}

COMMON_REQUIRED_FIELDS = ["event_id", "event_type", "timestamp_sim", "source"]


def validate_event(event_payload: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validates an event payload dictionary.
    Returns (is_valid: bool, message: str)
    """
    if not isinstance(event_payload, dict):
        return False, "Payload must be a JSON object / dict."

    # Check common fields
    for field in COMMON_REQUIRED_FIELDS:
        if field not in event_payload:
            return False, f"Missing required common field '{field}'."

    event_type = event_payload.get("event_type")
    if event_type not in SCHEMA_MAPPING:
        return False, f"Unknown or invalid event_type '{event_type}'. Must be one of {list(SCHEMA_MAPPING.keys())}."

    schema_file = SCHEMA_MAPPING[event_type]
    schema_path = os.path.join(SCHEMA_DIR, schema_file)

    if not os.path.exists(schema_path):
        return False, f"Schema file not found at {schema_path}"

    if HAS_JSONSCHEMA:
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            jsonschema.validate(instance=event_payload, schema=schema)
            return True, f"Event '{event_type}' is valid according to JSON Schema."
        except jsonschema.ValidationError as e:
            return False, f"Schema validation error for '{event_type}': {e.message}"
        except Exception as e:
            return False, f"Error validating schema: {str(e)}"
    else:
        # Fallback basic validation
        return True, f"Event '{event_type}' has basic valid header (jsonschema library not installed)."


def test_all_examples() -> bool:
    """Test all JSON example files in shared/examples/."""
    examples_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")
    all_passed = True
    print("--- Running Shared Event Schema Validation Tests ---")
    for filename in os.listdir(examples_dir):
        if filename.endswith(".json"):
            filepath = os.path.join(examples_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                payload = json.load(f)
            valid, msg = validate_event(payload)
            status = "PASS" if valid else "FAIL"
            print(f"[{status}] {filename}: {msg}")
            if not valid:
                all_passed = False
    return all_passed


if __name__ == "__main__":
    success = test_all_examples()
    if success:
        print("\nAll event schema validation tests PASSED successfully!")
    else:
        print("\nSome event schema validation tests FAILED.")
        exit(1)
