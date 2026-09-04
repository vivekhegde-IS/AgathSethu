from pathlib import Path
from ultralytics import YOLO


MODEL_PATH = (
    Path(__file__).resolve().parent
    / "models"
    / "number_plate"
    / "number_plate_detector.pt"
)

print("================================")
print("MODEL LOAD TEST")
print("================================")

print("Model path:")
print(MODEL_PATH)

print()
print("Checking model...")

if not MODEL_PATH.exists():
    raise FileNotFoundError(
        f"Model not found: {MODEL_PATH}"
    )

print("Model exists: TRUE")

print()
print("Loading YOLO model...")

model = YOLO(str(MODEL_PATH))

print()
print("MODEL LOADED SUCCESSFULLY")
print("Model task:", model.task)
print("================================")