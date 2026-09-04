from pathlib import Path

import cv2
from ultralytics import YOLO


BACKEND_DIR = Path(__file__).resolve().parent

MODEL_PATH = (
    BACKEND_DIR
    / "models"
    / "number_plate"
    / "number_plate_detector.pt"
)

IMAGE_PATH = Path(
    r"C:\Users\vivek\Downloads\major project\major project demo 1\AgathSethu\member3\backend\test_video_output\best_frame.jpg"
)

OUTPUT_PATH = (
    BACKEND_DIR
    / "all_plate_detections.jpg"
)


def main():

    print("=" * 70)
    print("DIRECT YOLO NUMBER-PLATE DETECTION TEST")
    print("=" * 70)

    print(f"Model: {MODEL_PATH}")
    print(f"Image: {IMAGE_PATH}")

    if not MODEL_PATH.exists():
        print("ERROR: YOLO model not found.")
        return

    if not IMAGE_PATH.exists():
        print("ERROR: Image not found.")
        print("Change IMAGE_PATH to the actual image path.")
        return

    print()
    print("Loading YOLO...")

    model = YOLO(str(MODEL_PATH))

    print("YOLO loaded.")
    print()

    image = cv2.imread(str(IMAGE_PATH))

    if image is None:
        print("ERROR: Could not read image.")
        return

    height, width = image.shape[:2]

    print(f"Image resolution: {width} x {height}")
    print()

    # ---------------------------------------------------------
    # VERY LOW CONFIDENCE TEST
    # ---------------------------------------------------------

    print("Running YOLO with conf=0.01...")
    print()

    results = model.predict(
        source=image,
        imgsz=1280,
        conf=0.01,
        max_det=100,
        save=False,
        verbose=False,
        device="cpu",
    )

    detections = []

    for result in results:

        if result.boxes is None:
            continue

        for i in range(len(result.boxes)):

            confidence = float(
                result.boxes.conf[i].item()
            )

            xyxy = (
                result.boxes.xyxy[i]
                .cpu()
                .numpy()
            )

            x1, y1, x2, y2 = [
                int(round(float(v)))
                for v in xyxy
            ]

            detections.append(
                {
                    "confidence": confidence,
                    "bbox": [
                        x1,
                        y1,
                        x2,
                        y2,
                    ],
                }
            )

    detections.sort(
        key=lambda x: x["confidence"],
        reverse=True,
    )

    print(
        f"Total detections: {len(detections)}"
    )

    print()

    if not detections:
        print(
            "YOLO detected NOTHING, even at conf=0.01."
        )

    else:

        for index, detection in enumerate(
            detections,
            start=1,
        ):

            print(
                f"{index:02d}. "
                f"confidence="
                f"{detection['confidence']:.6f} "
                f"bbox="
                f"{detection['bbox']}"
            )

    # ---------------------------------------------------------
    # DRAW ALL DETECTIONS
    # ---------------------------------------------------------

    annotated = image.copy()

    for index, detection in enumerate(
        detections,
        start=1,
    ):

        x1, y1, x2, y2 = (
            detection["bbox"]
        )

        confidence = (
            detection["confidence"]
        )

        cv2.rectangle(
            annotated,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            3,
        )

        label = (
            f"{index}: "
            f"{confidence:.3f}"
        )

        cv2.putText(
            annotated,
            label,
            (
                x1,
                max(30, y1 - 10),
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

    cv2.imwrite(
        str(OUTPUT_PATH),
        annotated,
    )

    print()
    print(
        f"Annotated image saved to:"
    )
    print(OUTPUT_PATH)

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()