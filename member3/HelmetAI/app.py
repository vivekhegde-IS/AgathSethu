from pathlib import Path
import json
import time
import uuid

import cv2
import numpy as np
import torch
from flask import Flask, render_template, request
from rapidocr_onnxruntime import RapidOCR
from ultralytics import YOLO
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "models" / "helmet_v4_final_best.pt"
ANPR_MODEL_PATH = BASE_DIR.parent / "backend" / "models" / "number_plate" / "number_plate_detector.pt"

UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}

NUMBER_PLATE = 0
RIDER = 1
WITH_HELMET = 2
WITHOUT_HELMET = 3
MOTORCYCLE = 4
HELMETAI_CLASSES = {RIDER, WITH_HELMET, WITHOUT_HELMET, MOTORCYCLE}

RIDER_CONFIDENCE = 0.40
HELMET_CONFIDENCE = 0.25
INFERENCE_SIZE = 1280

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024


def load_model():
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"V4 best.pt was not found at: {MODEL_PATH}")

    device = 0 if torch.cuda.is_available() else "cpu"
    print("=" * 60)
    print("HelmetAI inference server")
    print(f"Model: {MODEL_PATH}")
    print(f"CUDA available: {'YES' if torch.cuda.is_available() else 'NO'}")
    print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"Inference device: {device}")
    print("=" * 60)
    return YOLO(str(MODEL_PATH)), device


def load_anpr_model():
    if not ANPR_MODEL_PATH.is_file():
        raise FileNotFoundError(f"ANPR model was not found at: {ANPR_MODEL_PATH}")

    print(f"ANPR model: {ANPR_MODEL_PATH}")
    return YOLO(str(ANPR_MODEL_PATH))


model, DEVICE = load_model()
anpr_model = load_anpr_model()
anpr_ocr_reader = RapidOCR()
print("ANPR RapidOCR reader: ready")


def clamp_box(box, width, height):
    x1, y1, x2, y2 = [int(round(value)) for value in box]
    return (
        max(0, min(x1, width - 1)),
        max(0, min(y1, height - 1)),
        max(0, min(x2, width)),
        max(0, min(y2, height)),
    )


def box_center(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def intersection_area(first, second):
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    return max(0, x2 - x1) * max(0, y2 - y1)


def center_distance(first, second):
    first_center = box_center(first)
    second_center = box_center(second)
    return float(np.hypot(first_center[0] - second_center[0], first_center[1] - second_center[1]))


def associate_motorcycle_with_rider(rider_box, motorcycle_detections):
    if not motorcycle_detections:
        return None

    rider_width = rider_box[2] - rider_box[0]
    rider_height = rider_box[3] - rider_box[1]
    rider_scale = max(1.0, float(np.hypot(rider_width, rider_height)))

    def motorcycle_score(motorcycle):
        motorcycle_box = motorcycle["box"]
        overlap = intersection_area(rider_box, motorcycle_box)
        return center_distance(rider_box, motorcycle_box) / rider_scale - (overlap / rider_scale**2)

    return min(motorcycle_detections, key=motorcycle_score)


def associate_plate_with_motorcycle(motorcycle_box, plate_detections):
    if not plate_detections:
        return None

    motorcycle_x1, motorcycle_y1, motorcycle_x2, motorcycle_y2 = motorcycle_box
    motorcycle_width = max(1.0, motorcycle_x2 - motorcycle_x1)
    motorcycle_height = max(1.0, motorcycle_y2 - motorcycle_y1)

    candidates = []
    for plate in plate_detections:
        plate_box = plate["box"]
        plate_center_x, plate_center_y = box_center(plate["box"])
        horizontal_offset = abs(plate_center_x - (motorcycle_x1 + motorcycle_width / 2)) / motorcycle_width
        vertical_position = (plate_center_y - motorcycle_y1) / motorcycle_height
        overlap = intersection_area(motorcycle_box, plate_box)
        plate_area = max(1.0, (plate_box[2] - plate_box[0]) * (plate_box[3] - plate_box[1]))
        plate_inside_ratio = overlap / plate_area
        center_inside = (
            motorcycle_x1 <= plate_center_x <= motorcycle_x2
            and motorcycle_y1 <= plate_center_y <= motorcycle_y2
        )

        # A plate must be horizontally aligned with this vehicle and lie on
        # its body. This prevents a nearby vehicle's plate from winning on
        # center distance alone.
        if (
            not center_inside
            or plate_inside_ratio < 0.50
            or horizontal_offset > 0.65
            or vertical_position < -0.15
            or vertical_position > 1.15
        ):
            continue

        score = (
            horizontal_offset * 2.0
            + abs(vertical_position - 0.72)
            - plate_inside_ratio
            - min(1.0, plate["confidence"])
        )
        candidates.append((score, plate))

    if not candidates:
        return None

    return min(candidates, key=lambda candidate: candidate[0])[1]


def clean_ocr_text(text):
    return "".join(character for character in str(text).upper() if character.isalnum())


def read_anpr_plate(image, plate_box):
    x1, y1, x2, y2 = plate_box
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return ""

    candidates = []
    for scale in (1, 3, 5):
        prepared = crop if scale == 1 else cv2.resize(
            crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
        )
        try:
            results, _ = anpr_ocr_reader(prepared)
        except Exception as error:
            print(f"RapidOCR error: {error}")
            continue
        valid_results = []
        for result in results or []:
            if len(result) < 3:
                continue
            text = clean_ocr_text(result[1])
            confidence = float(result[2])
            if text and confidence >= 0.10:
                valid_results.append((result, text, confidence))

        if valid_results:
            ordered = sorted(
                valid_results,
                key=lambda item: (
                    sum(point[1] for point in item[0][0]) / len(item[0][0]),
                    sum(point[0] for point in item[0][0]) / len(item[0][0]),
                ),
            )
            combined = "".join(item[1] for item in ordered)
            confidence = sum(item[2] for item in ordered) / len(ordered)
            candidates.append((confidence, combined))

    return max(candidates, default=(0.0, ""))[1]


def detect_anpr_plates(image, offset=(0, 0)):
    results = anpr_model.predict(
        source=image,
        imgsz=INFERENCE_SIZE,
        conf=0.05,
        device=DEVICE,
        max_det=20,
        save=False,
        verbose=False,
    )
    detections = extract_detections(results[0], image.shape) if results else []
    offset_x, offset_y = offset
    for detection in detections:
        x1, y1, x2, y2 = detection["box"]
        detection["box"] = (x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y)
    return [item for item in detections if item["class_id"] == NUMBER_PLATE]


def vehicle_roi(frame, vehicle_box):
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = clamp_box(vehicle_box, width, height)
    return frame[y1:y2, x1:x2], (x1, y1)


def rider_vehicle_roi(frame, rider_box):
    rider_x1, rider_y1, rider_x2, rider_y2 = rider_box
    rider_width = max(1.0, rider_x2 - rider_x1)
    rider_height = max(1.0, rider_y2 - rider_y1)
    x1 = rider_x1 - 1.3 * rider_width
    y1 = rider_y1
    x2 = rider_x2 + 1.3 * rider_width
    y2 = rider_y1 + 6.5 * rider_height
    return vehicle_roi(frame, (x1, y1, x2, y2))


def attach_violation_plates(image, detections, riders):
    motorcycles = [item for item in detections if item["class_id"] == MOTORCYCLE]
    plates = [item for item in detections if item["class_id"] == NUMBER_PLATE]
    assigned_plate_ids = set()
    roi_plates_to_draw = []

    for rider in riders:
        rider["motorcycle"] = None
        rider["plate"] = None
        if rider["has_helmet"]:
            continue

        motorcycle = associate_motorcycle_with_rider(rider["box"], motorcycles)
        rider["motorcycle"] = motorcycle
        if motorcycle is None:
            roi, offset = rider_vehicle_roi(image, rider["box"])
            association_box = (
                offset[0],
                offset[1],
                offset[0] + roi.shape[1],
                offset[1] + roi.shape[0],
            )
        else:
            roi, offset = vehicle_roi(image, motorcycle["box"])
            association_box = motorcycle["box"]

        roi_plates = detect_anpr_plates(roi, offset)
        available_plates = [plate for plate in roi_plates if id(plate) not in assigned_plate_ids]
        plate = associate_plate_with_motorcycle(association_box, available_plates)
        if plate is None:
            available_plates = [plate for plate in plates if id(plate) not in assigned_plate_ids]
            plate = associate_plate_with_motorcycle(association_box, available_plates)
        rider["vehicle_roi"] = association_box
        rider["plate"] = plate
        if plate is not None and "ocr_text" not in plate:
            assigned_plate_ids.add(id(plate))
            plate["ocr_text"] = read_anpr_plate(image, plate["box"])
            if plate not in plates:
                roi_plates_to_draw.append(plate)

    return roi_plates_to_draw


def associate_helmet_with_rider(rider_box, helmet_detections):
    x1, y1, x2, y2 = rider_box
    rider_width = x2 - x1
    rider_height = y2 - y1

    # The upper central 30 percent of the rider is the estimated head region.
    head_region = (
        x1 + 0.20 * rider_width,
        y1,
        x1 + 0.80 * rider_width,
        y1 + 0.30 * rider_height,
    )
    head_center = box_center(head_region)
    head_width = head_region[2] - head_region[0]
    head_height = head_region[3] - head_region[1]
    max_distance = max(20.0, 0.55 * float(np.hypot(head_width, head_height)))

    for helmet in helmet_detections:
        helmet_box = helmet["box"]
        helmet_center = box_center(helmet_box)
        helmet_width = max(1.0, helmet_box[2] - helmet_box[0])
        helmet_height = max(1.0, helmet_box[3] - helmet_box[1])
        overlap = intersection_area(head_region, helmet_box)
        helmet_area = helmet_width * helmet_height
        center_inside = (
            head_region[0] <= helmet_center[0] <= head_region[2]
            and head_region[1] <= helmet_center[1] <= head_region[3]
        )
        close_to_head = np.hypot(
            helmet_center[0] - head_center[0],
            helmet_center[1] - head_center[1],
        ) <= max_distance

        if overlap / helmet_area >= 0.20 or center_inside or close_to_head:
            return True

    return False


def extract_detections(result, image_shape):
    height, width = image_shape[:2]
    detections = []
    if result.boxes is None:
        return detections

    for box in result.boxes:
        class_id = int(box.cls.item())
        confidence = float(box.conf.item())
        coordinates = clamp_box(box.xyxy[0].tolist(), width, height)
        detections.append(
            {"class_id": class_id, "confidence": confidence, "box": coordinates}
        )
    return detections


def run_inference(image):
    results = model.predict(
        source=image,
        imgsz=INFERENCE_SIZE,
        conf=0.20,
        device=DEVICE,
        max_det=100,
        save=False,
        verbose=False,
    )
    helmet_detections = extract_detections(results[0], image.shape) if results else []
    helmet_detections = [
        item for item in helmet_detections if item["class_id"] in HELMETAI_CLASSES
    ]

    anpr_detections = detect_anpr_plates(image)

    detections = helmet_detections + anpr_detections
    helmets = [
        item
        for item in detections
        if item["class_id"] == WITH_HELMET and item["confidence"] >= HELMET_CONFIDENCE
    ]
    riders = [
        item
        for item in detections
        if item["class_id"] == RIDER and item["confidence"] >= RIDER_CONFIDENCE
    ]

    for rider in riders:
        rider["has_helmet"] = associate_helmet_with_rider(rider["box"], helmets)

    roi_plates = attach_violation_plates(image, anpr_detections, riders)
    anpr_detections.extend(roi_plates)
    detections.extend(roi_plates)
    return detections, riders


def draw_label(image, text, origin, color):
    x, y = origin
    cv2.putText(
        image,
        text,
        (x, max(24, y)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        color,
        2,
        cv2.LINE_AA,
    )


def draw_results(image, detections, riders):
    annotated = image.copy()
    rider_by_box = {rider["box"]: rider for rider in riders}
    violation_motorcycles = {
        rider["motorcycle"]["box"]
        for rider in riders
        if not rider["has_helmet"] and rider.get("motorcycle") is not None
    }

    for detection in detections:
        class_id = detection["class_id"]
        box = detection["box"]
        x1, y1, x2, y2 = box

        if class_id == RIDER and box in rider_by_box:
            rider = rider_by_box[box]
            color = (0, 200, 0) if rider["has_helmet"] else (0, 0, 255)
            if rider["has_helmet"]:
                label = "Rider - HELMET"
            else:
                plate_text = rider.get("plate", {}).get("ocr_text", "") if rider.get("plate") else ""
                label = f"NO HELMET - {plate_text}" if plate_text else "NO HELMET - VIOLATION"
        elif class_id == WITH_HELMET and detection["confidence"] >= HELMET_CONFIDENCE:
            color, label = (0, 200, 0), "With Helmet"
        elif class_id == MOTORCYCLE:
            color = (0, 0, 255) if box in violation_motorcycles else (0, 200, 0)
            label = "Motorcycle - VIOLATION" if box in violation_motorcycles else "Motorcycle"
        elif class_id == NUMBER_PLATE:
            color = (255, 170, 0)
            label = f"Number Plate: {detection.get('ocr_text', '')}" if detection.get("ocr_text") else "Number Plate"
        else:
            continue

        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 3)
        draw_label(annotated, label, (x1, y1 - 8), color)

    return annotated


def build_summary(detections, riders):
    with_helmet = sum(rider["has_helmet"] for rider in riders)
    without_helmet = len(riders) - with_helmet
    violation_plates = []
    for rider in riders:
        if rider["has_helmet"]:
            continue
        plate = rider.get("plate")
        violation_plates.append(
            {
                "plate": plate.get("ocr_text", "") if plate else "",
                "readable": bool(plate and plate.get("ocr_text")),
            }
        )
    violation_records = []
    for rider in riders:
        if rider["has_helmet"]:
            continue
        plate = rider.get("plate")
        motorcycle = rider.get("motorcycle")
        vehicle_box = motorcycle["box"] if motorcycle else rider.get("vehicle_roi")
        violation_records.append(
            {
                "violation": "NO HELMET",
                "vehicle_box": list(vehicle_box) if vehicle_box else None,
                "plate_box": list(plate["box"]) if plate else None,
                "plate_number": plate.get("ocr_text", "") if plate else "",
                "plate_source": "ANPR" if plate else None,
            }
        )
    return {
        "riders": len(riders),
        "with_helmet": with_helmet,
        "without_helmet": without_helmet,
        "violations": without_helmet,
        "motorcycles": sum(item["class_id"] == MOTORCYCLE for item in detections),
        "number_plates": sum(item["class_id"] == NUMBER_PLATE for item in detections),
        "status": "VIOLATION DETECTED" if without_helmet else "NO VIOLATION DETECTED",
        "violation_plates": violation_plates,
        "violation_records": violation_records,
    }


def save_summary_json(summary, json_path):
    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2)


def save_image_result(image, detections, riders):
    annotated = draw_results(image, detections, riders)
    filename = f"result_{uuid.uuid4().hex}.jpg"
    cv2.imwrite(str(UPLOAD_DIR / filename), annotated)
    summary = build_summary(detections, riders)
    json_filename = f"result_{uuid.uuid4().hex}.json"
    summary["result_json"] = json_filename
    save_summary_json(summary, UPLOAD_DIR / json_filename)
    return filename, summary


def process_video(input_path, output_path, evidence_path=None):
    print(f"[ROUTINE DEBUG] OPENING VIDEO: {input_path}", flush=True)
    capture = cv2.VideoCapture(str(input_path))
    print(f"[ROUTINE DEBUG] PIPELINE VIDEO OPENED: {capture.isOpened()}", flush=True)
    if not capture.isOpened():
        raise ValueError("Unable to open the uploaded video.")

    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(
        str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    print(f"[ROUTINE DEBUG] OUTPUT WRITER OPENED: {writer.isOpened()}", flush=True)
    if not writer.isOpened():
        capture.release()
        raise ValueError("Unable to create the processed video.")

    best_summary = build_summary([], [])
    best_annotated = None
    processed_frames = 0
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            processed_frames += 1
            if processed_frames % 100 == 0:
                print(f"[ROUTINE DEBUG] PROCESSING FRAME: {processed_frames}", flush=True)
            if processed_frames == 1:
                print("[ROUTINE DEBUG] STARTING FIRST FRAME INFERENCE", flush=True)
            detections, riders = run_inference(frame)
            if processed_frames == 1:
                print("[ROUTINE DEBUG] FIRST FRAME INFERENCE RETURNED", flush=True)
            annotated = draw_results(frame, detections, riders)
            writer.write(annotated)
            current_summary = build_summary(detections, riders)
            if (
                current_summary["violations"] > best_summary["violations"]
                or (
                    current_summary["violations"] == best_summary["violations"]
                    and current_summary["riders"] >= best_summary["riders"]
                )
            ):
                best_summary = current_summary
                best_annotated = annotated.copy()
    finally:
        capture.release()
        writer.release()
    json_path = Path(output_path).with_suffix(".json")
    best_summary["result_json"] = str(json_path)
    save_summary_json(best_summary, json_path)
    if evidence_path is not None and best_annotated is not None and best_summary["violations"]:
        cv2.imwrite(str(evidence_path), best_annotated)
    print(f"[ROUTINE DEBUG] FRAMES PROCESSED: {processed_frames}", flush=True)
    return best_summary


ROUTINE_VIOLATION_FRAME_SKIP = 5


def process_routine_video(input_path, evidence_path):
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise ValueError("Unable to open the uploaded video.")

    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"[ROUTINE] Video opened: {input_path}", flush=True)
    print(f"[ROUTINE] Total frames: {total_frames}", flush=True)
    print(f"[ROUTINE] Sampling interval: {ROUTINE_VIOLATION_FRAME_SKIP}", flush=True)

    best_summary = build_summary([], [])
    best_annotated = None
    inspected_frames = 0
    frame_number = -1
    start_time = time.perf_counter()

    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            frame_number += 1
            if frame_number % ROUTINE_VIOLATION_FRAME_SKIP != 0:
                continue

            inspected_frames += 1
            print(f"[ROUTINE] Sampled frame: {frame_number}", flush=True)
            results = model.predict(
                source=frame,
                imgsz=INFERENCE_SIZE,
                conf=0.20,
                device=DEVICE,
                max_det=100,
                save=False,
                verbose=False,
            )
            helmet_detections = extract_detections(results[0], frame.shape) if results else []
            helmet_detections = [
                item for item in helmet_detections if item["class_id"] in HELMETAI_CLASSES
            ]
            helmets = [
                item for item in helmet_detections
                if item["class_id"] == WITH_HELMET and item["confidence"] >= HELMET_CONFIDENCE
            ]
            riders = [
                item for item in helmet_detections
                if item["class_id"] == RIDER and item["confidence"] >= RIDER_CONFIDENCE
            ]
            for rider in riders:
                rider["has_helmet"] = associate_helmet_with_rider(rider["box"], helmets)

            violating_riders = [rider for rider in riders if not rider["has_helmet"]]
            if not violating_riders:
                continue

            print("[ROUTINE] VIOLATION CANDIDATE FOUND", flush=True)
            print(f"[ROUTINE] Frame: {frame_number}", flush=True)
            print("[ROUTINE] Type: NO HELMET", flush=True)
            roi_plates = attach_violation_plates(frame, helmet_detections, riders)
            detections = helmet_detections + roi_plates
            summary = build_summary(detections, riders)
            annotated = draw_results(frame, detections, riders)
            violation = (summary.get("violation_records") or [None])[0]
            plate_number = violation.get("plate_number") if violation else ""
            print(f"[ROUTINE] ANPR RUN FOR CANDIDATE", flush=True)
            print(f"[ROUTINE] Plate: {plate_number or 'unknown'}", flush=True)

            if summary["violations"] > best_summary["violations"] or (
                summary["violations"] == best_summary["violations"]
                and bool(plate_number)
                and not best_summary.get("violation_plates", [{}])[0].get("readable", False)
            ):
                best_summary = summary
                best_annotated = annotated

            if summary["violations"] and plate_number:
                cv2.imwrite(str(evidence_path), annotated)
                print(f"[ROUTINE] EVIDENCE SAVED: {evidence_path}", flush=True)
                print("[ROUTINE] VALID VIOLATION FOUND - EARLY EXIT", flush=True)
                break
    finally:
        capture.release()

    if best_summary["violations"] and best_annotated is not None and not evidence_path.exists():
        cv2.imwrite(str(evidence_path), best_annotated)
        print(f"[ROUTINE] EVIDENCE SAVED: {evidence_path}", flush=True)

    json_path = Path(evidence_path).with_suffix(".json")
    best_summary["result_json"] = str(json_path)
    save_summary_json(best_summary, json_path)
    print(f"[ROUTINE] JOB COMPLETED", flush=True)
    print(f"[ROUTINE] Frames inspected: {inspected_frames}", flush=True)
    print(f"[ROUTINE] Total video frames: {total_frames}", flush=True)
    print(f"[ROUTINE] Processing time: {time.perf_counter() - start_time:.2f}s", flush=True)
    return best_summary


def render_page(**context):
    defaults = {"summary": None, "result_image": None, "result_video": None, "error": None}
    defaults.update(context)
    return render_template("index.html", **defaults)


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_page()

    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return render_page(error="Choose an image or video first."), 400

    extension = Path(secure_filename(uploaded.filename)).suffix.lower()
    if extension not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
        return render_page(error="Supported files: JPG, PNG, WEBP, MP4, AVI, MOV, MKV."), 400

    unique_name = f"input_{uuid.uuid4().hex}{extension}"
    input_path = UPLOAD_DIR / unique_name
    uploaded.save(str(input_path))

    try:
        if extension in IMAGE_EXTENSIONS:
            image = cv2.imread(str(input_path))
            if image is None:
                raise ValueError("Unable to decode the uploaded image.")
            detections, riders = run_inference(image)
            result_name, summary = save_image_result(image, detections, riders)
            return render_page(result_image=result_name, summary=summary)

        output_name = f"result_{uuid.uuid4().hex}.mp4"
        summary = process_video(input_path, UPLOAD_DIR / output_name)
        return render_page(result_video=output_name, summary=summary)
    except Exception as error:
        print(f"Inference error: {error}")
        return render_page(error=f"Inference failed: {error}"), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
