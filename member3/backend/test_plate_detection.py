from pathlib import Path

import cv2
from ultralytics import YOLO


BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = (
    BASE_DIR
    / "models"
    / "number_plate"
    / "number_plate_detector.pt"
)

IMAGE_PATH = BASE_DIR / "test_plate.jpeg"

OUTPUT_PATH = BASE_DIR / "test_plate_result.jpeg"


print("================================")
print("NUMBER PLATE DETECTION TEST")
print("================================")

print()
print("Model:")
print(MODEL_PATH)

print()
print("Image:")
print(IMAGE_PATH)

if not MODEL_PATH.exists():
    raise FileNotFoundError(
        f"Model not found: {MODEL_PATH}"
    )

if not IMAGE_PATH.exists():
    raise FileNotFoundError(
        f"Test image not found: {IMAGE_PATH}"
    )

print()
print("Loading model...")

model = YOLO(
    str(MODEL_PATH)
)

print("Model loaded successfully.")

print()
print("Reading image...")

frame = cv2.imread(
    str(IMAGE_PATH)
)

if frame is None:
    raise RuntimeError(
        "OpenCV could not read the test image."
    )

print(
    "Image resolution:",
    frame.shape[1],
    "x",
    frame.shape[0]
)

print()
print("Running YOLO plate detection...")

results = model.predict(
    source=frame,
    imgsz=1280,
    conf=0.20,
    device="cpu",
    max_det=50,
    save=False,
    verbose=False
)

annotated = frame.copy()

detection_count = 0


for result in results:

    if result.boxes is None:
        continue

    for box in result.boxes:

        detection_count += 1

        confidence = float(
            box.conf[0]
        )

        x1, y1, x2, y2 = map(
            int,
            box.xyxy[0].tolist()
        )

        print()
        print(
            f"Detection {detection_count}"
        )

        print(
            "Bounding box:",
            x1,
            y1,
            x2,
            y2
        )

        print(
            "Confidence:",
            round(confidence, 4)
        )

        cv2.rectangle(
            annotated,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            3
        )

        cv2.putText(
            annotated,
            f"Plate {confidence:.2f}",
            (x1, max(30, y1 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2
        )


cv2.imwrite(
    str(OUTPUT_PATH),
    annotated
)

print()
print("================================")
print("DETECTION COMPLETE")
print("================================")

print(
    "Total detections:",
    detection_count
)

print()
print("Result image:")
print(OUTPUT_PATH)