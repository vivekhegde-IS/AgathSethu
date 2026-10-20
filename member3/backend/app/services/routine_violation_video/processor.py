from __future__ import annotations

import json
import math
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from ultralytics import YOLO


# ============================================================
# PATHS
# ============================================================

BACKEND_DIR = Path(__file__).resolve().parents[3]

MODEL_PATH = (
    BACKEND_DIR
    / "models"
    / "number_plate"
    / "number_plate_detector.pt"
)


# ============================================================
# GLOBAL MODELS
# ============================================================

_yolo_model = None
_ocr_engine = None


def get_yolo_model():
    global _yolo_model

    if _yolo_model is None:
        print("Loading YOLO number-plate detector...")
        _yolo_model = YOLO(str(MODEL_PATH))
        print("YOLO loaded.")

    return _yolo_model


def get_ocr_engine():
    global _ocr_engine

    if _ocr_engine is None:
        print("Loading RapidOCR...")
        _ocr_engine = RapidOCR()
        print("RapidOCR loaded.")

    return _ocr_engine


# ============================================================
# INDIAN REGISTRATION CODES
# ============================================================

INDIAN_STATE_CODES = {
    "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD",
    "DL", "DN", "GA", "GJ", "HR", "HP", "JK", "JH",
    "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
    "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK",
    "TN", "TR", "TS", "UK", "UP", "WB"
}


# ============================================================
# OCR NORMALIZATION
# ============================================================

def clean_ocr_text(text: str) -> str:
    if not text:
        return ""

    text = str(text).upper()

    return re.sub(
        r"[^A-Z0-9]",
        "",
        text
    )


def alpha_position_fix(text: str) -> str:
    """
    Corrections only for positions expected to contain letters.
    """

    mapping = {
        "0": "O",
        "1": "I",
        "2": "Z",
        "5": "S",
        "6": "G",
        "7": "T",
        "8": "B",
    }

    return "".join(
        mapping.get(char, char)
        for char in text
    )


def numeric_position_fix(text: str) -> str:
    """
    Corrections only for positions expected to contain digits.
    """

    mapping = {
        "O": "0",
        "D": "0",
        "Q": "0",
        "I": "1",
        "L": "1",
        "Z": "2",
        "S": "5",
        "B": "8",
        "G": "6",
        "T": "7",
    }

    return "".join(
        mapping.get(char, char)
        for char in text
    )


def normalize_plate(text: str) -> str | None:

    text = clean_ocr_text(text)

    if len(text) != 10:
        return None

    state = alpha_position_fix(
        text[:2]
    )

    district = numeric_position_fix(
        text[2:4]
    )

    series = alpha_position_fix(
        text[4:6]
    )

    number = numeric_position_fix(
        text[6:10]
    )

    if state not in INDIAN_STATE_CODES:
        return None

    if not district.isdigit():
        return None

    if not re.fullmatch(
        r"[A-Z]{2}",
        series
    ):
        return None

    if not number.isdigit():
        return None

    return (
        state
        + district
        + series
        + number
    )


def format_plate(plate: str | None) -> str | None:

    if not plate:
        return None

    if len(plate) != 10:
        return plate

    return (
        f"{plate[:2]} "
        f"{plate[2:4]} "
        f"{plate[4:6]} "
        f"{plate[6:]}"
    )


# ============================================================
# VIDEO INFORMATION
# ============================================================

def get_video_info(
    video_path: Path
) -> dict[str, Any]:

    cap = cv2.VideoCapture(
        str(video_path)
    )

    if not cap.isOpened():
        raise RuntimeError(
            f"Unable to open video: {video_path}"
        )

    fps = float(
        cap.get(cv2.CAP_PROP_FPS)
    )

    frame_count = int(
        cap.get(cv2.CAP_PROP_FRAME_COUNT)
    )

    width = int(
        cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    )

    height = int(
        cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    )

    cap.release()

    if fps <= 0:
        fps = 30.0

    duration = (
        frame_count / fps
        if frame_count > 0
        else 0.0
    )

    return {
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration_seconds": duration,
    }


# ============================================================
# ADAPTIVE FRAME COUNT
# ============================================================

def calculate_frame_count(
    duration: float,
    frame_count: int
) -> int:
    """
    Duration-based adaptive sampling.

    The number of YOLO calls increases with video duration,
    but has a hard upper limit.

    This prevents a 60-second video from causing hundreds
    of YOLO inferences.

    Approximate initial sampling:

        <= 3 sec    -> 5 frames
        <= 6 sec    -> 6 frames
        <= 10 sec   -> 8 frames
        <= 20 sec   -> 10 frames
        <= 30 sec   -> 12 frames
        <= 60 sec   -> 16 frames
        > 60 sec    -> 20 frames maximum
    """

    if frame_count <= 0:
        return 0

    if duration <= 3:
        count = 5

    elif duration <= 6:
        count = 6

    elif duration <= 10:
        count = 8

    elif duration <= 20:
        count = 10

    elif duration <= 30:
        count = 12

    elif duration <= 60:
        count = 16

    else:
        count = 20

    return min(
        count,
        frame_count
    )


def generate_sample_indices(
    frame_count: int,
    duration: float
) -> list[int]:

    count = calculate_frame_count(
        duration,
        frame_count
    )

    if count <= 0:
        return []

    if count == 1:
        return [0]

    indices = np.linspace(
        0,
        frame_count - 1,
        count,
        dtype=np.int32
    )

    return sorted(
        set(
            int(index)
            for index in indices
        )
    )


# ============================================================
# FRAME READING
# ============================================================

def read_selected_frames(
    video_path: Path,
    indices: list[int]
) -> dict[int, np.ndarray]:

    wanted = set(indices)

    frames = {}

    if not wanted:
        return frames

    cap = cv2.VideoCapture(
        str(video_path)
    )

    if not cap.isOpened():
        return frames

    frame_index = 0

    while True:

        success, frame = cap.read()

        if not success:
            break

        if frame_index in wanted:

            frames[frame_index] = frame

            if len(frames) == len(wanted):
                break

        frame_index += 1

    cap.release()

    return frames


# ============================================================
# IMAGE QUALITY
# ============================================================

def calculate_sharpness(
    image: np.ndarray
) -> float:

    if image is None or image.size == 0:
        return 0.0

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    return float(
        cv2.Laplacian(
            gray,
            cv2.CV_64F
        ).var()
    )


def calculate_brightness(
    image: np.ndarray
) -> float:

    if image is None or image.size == 0:
        return 0.0

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    return float(
        np.mean(gray)
    )


def calculate_quality(
    crop: np.ndarray,
    detector_confidence: float,
    frame_width: int,
    frame_height: int
) -> float:

    if crop is None or crop.size == 0:
        return 0.0

    h, w = crop.shape[:2]

    if h <= 0 or w <= 0:
        return 0.0

    aspect_ratio = w / h

    if 2.0 <= aspect_ratio <= 6.0:
        aspect_score = 1.0

    elif 1.5 <= aspect_ratio <= 7.0:
        aspect_score = 0.7

    else:
        aspect_score = 0.3

    sharp = calculate_sharpness(
        crop
    )

    sharp_score = (
        1.0
        - math.exp(
            -sharp / 150.0
        )
    )

    area_ratio = (
        (w * h)
        / max(
            1,
            frame_width * frame_height
        )
    )

    area_score = min(
        1.0,
        math.sqrt(
            area_ratio / 0.02
        )
    )

    brightness = calculate_brightness(
        crop
    )

    if 40 <= brightness <= 225:
        brightness_score = 1.0

    elif 25 <= brightness <= 240:
        brightness_score = 0.65

    else:
        brightness_score = 0.3

    return float(
        0.45 * detector_confidence
        + 0.25 * sharp_score
        + 0.15 * area_score
        + 0.10 * aspect_score
        + 0.05 * brightness_score
    )


# ============================================================
# BOX FUNCTIONS
# ============================================================

def crop_from_box(
    frame: np.ndarray,
    box: list[int],
    padding: float = 0.08
) -> np.ndarray | None:

    frame_height, frame_width = (
        frame.shape[:2]
    )

    x1, y1, x2, y2 = box

    box_width = x2 - x1
    box_height = y2 - y1

    pad_x = int(
        box_width * padding
    )

    pad_y = int(
        box_height * padding
    )

    x1 = max(
        0,
        x1 - pad_x
    )

    y1 = max(
        0,
        y1 - pad_y
    )

    x2 = min(
        frame_width - 1,
        x2 + pad_x
    )

    y2 = min(
        frame_height - 1,
        y2 + pad_y
    )

    if x2 <= x1 or y2 <= y1:
        return None

    crop = frame[
        y1:y2,
        x1:x2
    ]

    if crop.size == 0:
        return None

    return crop.copy()


def box_center(
    box: list[int]
) -> tuple[float, float]:

    x1, y1, x2, y2 = box

    return (
        (x1 + x2) / 2.0,
        (y1 + y2) / 2.0
    )


def center_distance(
    box1: list[int],
    box2: list[int],
    width: int,
    height: int
) -> float:

    c1 = box_center(box1)
    c2 = box_center(box2)

    dx = (
        c1[0] - c2[0]
    ) / max(
        1,
        width
    )

    dy = (
        c1[1] - c2[1]
    ) / max(
        1,
        height
    )

    return math.sqrt(
        dx * dx + dy * dy
    )


# ============================================================
# YOLO DETECTION
# ============================================================

def detect_plates_in_frame(
    model,
    frame: np.ndarray,
    frame_index: int,
    fps: float
) -> list[dict[str, Any]]:

    height, width = frame.shape[:2]

    results = model.predict(
        source=frame,

        # Keep enough spatial resolution for small plates.
        imgsz=1280,

        # Low enough to recover weaker visible plates.
        conf=0.05,

        max_det=20,

        save=False,

        verbose=False,

        device="cpu"
    )

    detections = []

    for result in results:

        if result.boxes is None:
            continue

        for i in range(
            len(result.boxes)
        ):

            confidence = float(
                result.boxes.conf[
                    i
                ].item()
            )

            coordinates = (
                result.boxes.xyxy[
                    i
                ]
                .cpu()
                .numpy()
            )

            x1, y1, x2, y2 = [
                int(round(float(v)))
                for v in coordinates
            ]

            x1 = max(
                0,
                min(
                    width - 1,
                    x1
                )
            )

            y1 = max(
                0,
                min(
                    height - 1,
                    y1
                )
            )

            x2 = max(
                0,
                min(
                    width - 1,
                    x2
                )
            )

            y2 = max(
                0,
                min(
                    height - 1,
                    y2
                )
            )

            if x2 <= x1 or y2 <= y1:
                continue

            box = [
                x1,
                y1,
                x2,
                y2
            ]

            crop = crop_from_box(
                frame,
                box
            )

            if crop is None:
                continue

            quality = calculate_quality(
                crop,
                confidence,
                width,
                height
            )

            detections.append(
                {
                    "frame_index": frame_index,
                    "timestamp": (
                        frame_index / fps
                    ),
                    "bbox": box,
                    "confidence": confidence,
                    "quality": quality,
                    "sharpness": calculate_sharpness(
                        crop
                    ),
                    "crop": crop
                }
            )

    return detections


# ============================================================
# GROUP REPEATED DETECTIONS
# ============================================================

def group_detections(
    detections: list[dict[str, Any]],
    width: int,
    height: int
) -> list[list[dict[str, Any]]]:

    """
    Group detections that are likely the same physical
    plate across sampled frames.

    This is NOT the vehicle tracker.

    It is only used to prevent repeated ANPR OCR.
    """

    detections = sorted(
        detections,
        key=lambda x: x["frame_index"]
    )

    groups = []

    for detection in detections:

        best_group = None
        best_distance = float("inf")

        for group in groups:

            last_detection = group[-1]

            frame_gap = (
                detection["frame_index"]
                - last_detection["frame_index"]
            )

            # If the temporal gap is too large,
            # don't associate automatically.
            if frame_gap > 15:
                continue

            distance = center_distance(
                detection["bbox"],
                last_detection["bbox"],
                width,
                height
            )

            if distance < 0.08:

                if distance < best_distance:

                    best_distance = distance
                    best_group = group

        if best_group is None:

            groups.append(
                [detection]
            )

        else:

            best_group.append(
                detection
            )

    return groups


# ============================================================
# SELECT BEST DETECTIONS PER GROUP
# ============================================================

def select_best_group_detections(
    group: list[dict[str, Any]]
) -> list[dict[str, Any]]:

    """
    We don't OCR every frame of the same plate.

    Select at most TWO strong temporal observations.
    """

    ranked = sorted(
        group,
        key=lambda x: (
            x["quality"],
            x["confidence"],
            x["sharpness"]
        ),
        reverse=True
    )

    selected = []

    for detection in ranked:

        if not selected:

            selected.append(
                detection
            )

            continue

        # Second frame should provide temporal
        # diversity rather than being almost identical.
        different_frame = all(
            abs(
                detection["frame_index"]
                - item["frame_index"]
            ) >= 2
            for item in selected
        )

        if different_frame:

            selected.append(
                detection
            )

        if len(selected) >= 2:
            break

    return selected


# ============================================================
# OCR PREPROCESSING
# ============================================================

def upscale_plate(
    crop: np.ndarray
) -> np.ndarray:

    if crop is None or crop.size == 0:
        return crop

    height, width = crop.shape[:2]

    target_height = 180

    scale = max(
        2.0,
        target_height / max(
            1,
            height
        )
    )

    new_width = max(
        1,
        int(width * scale)
    )

    new_height = max(
        1,
        int(height * scale)
    )

    return cv2.resize(
        crop,
        (
            new_width,
            new_height
        ),
        interpolation=cv2.INTER_CUBIC
    )


def preprocess_primary(
    crop: np.ndarray
) -> np.ndarray:

    image = upscale_plate(
        crop
    )

    lab = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2LAB
    )

    l_channel, a_channel, b_channel = (
        cv2.split(lab)
    )

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    l_channel = clahe.apply(
        l_channel
    )

    enhanced = cv2.merge(
        (
            l_channel,
            a_channel,
            b_channel
        )
    )

    return cv2.cvtColor(
        enhanced,
        cv2.COLOR_LAB2BGR
    )


def preprocess_sharpened(
    crop: np.ndarray
) -> np.ndarray:

    image = preprocess_primary(
        crop
    )

    blur = cv2.GaussianBlur(
        image,
        (0, 0),
        1.2
    )

    return cv2.addWeighted(
        image,
        1.6,
        blur,
        -0.6,
        0
    )


# ============================================================
# RAPIDOCR
# ============================================================

def run_rapidocr(
    image: np.ndarray
) -> list[dict[str, Any]]:

    engine = get_ocr_engine()

    try:

        result, _ = engine(
            image
        )

    except Exception as exc:

        print(
            f"RapidOCR error: {exc}"
        )

        return []

    observations = []

    if result is None:
        return observations

    for item in result:

        if item is None or len(item) < 3:
            continue

        text = clean_ocr_text(
            item[1]
        )

        confidence = float(
            item[2]
        )

        if not text:
            continue

        observations.append(
            {
                "text": text,
                "confidence": confidence
            }
        )

    return observations


def ocr_plate_crop(
    crop: np.ndarray
) -> list[dict[str, Any]]:

    """
    Maximum two OCR preprocessing variants.

    Primary first.
    Sharpened only if the primary result doesn't
    immediately provide a valid registration number.
    """

    all_results = []

    primary = preprocess_primary(
        crop
    )

    print(
        "      RapidOCR: primary"
    )

    primary_results = run_rapidocr(
        primary
    )

    for result in primary_results:

        all_results.append(
            {
                **result,
                "variant": "primary"
            }
        )

    # Stop immediately if a valid plate was found.
    for result in primary_results:

        if normalize_plate(
            result["text"]
        ):

            return all_results

    # Second attempt.
    sharpened = preprocess_sharpened(
        crop
    )

    print(
        "      RapidOCR: sharpened"
    )

    sharpened_results = run_rapidocr(
        sharpened
    )

    for result in sharpened_results:

        all_results.append(
            {
                **result,
                "variant": "sharpened"
            }
        )

    return all_results


# ============================================================
# OCR STRING SIMILARITY
# ============================================================

def hamming_distance(
    a: str,
    b: str
) -> int:

    if len(a) != len(b):
        return max(
            len(a),
            len(b)
        )

    return sum(
        x != y
        for x, y in zip(a, b)
    )


# ============================================================
# MERGE OCR VARIANTS
# ============================================================

def merge_similar_plates(
    observations: list[dict[str, Any]]
) -> list[dict[str, Any]]:

    """
    Prevent OCR mistakes from becoming separate vehicles.

    Example:

        KA51AE0984
        KA51AE0984
        KA51AE0982

    becomes:

        KA51AE0984

    The weaker one-character variant is absorbed into
    the stronger plate.

    IMPORTANT:
    If TWO different plates both have strong multi-frame
    evidence, they are NOT merged.
    """

    if not observations:
        return []

    grouped = defaultdict(list)

    for observation in observations:

        grouped[
            observation["plate"]
        ].append(
            observation
        )

    plate_groups = [
        {
            "plate": plate,
            "observations": items
        }
        for plate, items
        in grouped.items()
    ]

    # Strongest evidence first.
    plate_groups.sort(
        key=lambda group: (
            len(group["observations"]),
            len(
                set(
                    x["frame_index"]
                    for x in group[
                        "observations"
                    ]
                )
            ),
            max(
                x["confidence"]
                for x in group[
                    "observations"
                ]
            )
        ),
        reverse=True
    )

    final_groups = []

    for group in plate_groups:

        plate = group["plate"]

        unique_frames = len(
            set(
                x["frame_index"]
                for x in group[
                    "observations"
                ]
            )
        )

        merged = False

        for existing in final_groups:

            existing_plate = existing[
                "plate"
            ]

            existing_unique_frames = len(
                set(
                    x["frame_index"]
                    for x in existing[
                        "observations"
                    ]
                )
            )

            distance = hamming_distance(
                plate,
                existing_plate
            )

            # ------------------------------------------------
            # Conservative fuzzy merge
            # ------------------------------------------------
            #
            # Only merge if:
            #
            # 1. Exactly one character differs.
            # 2. Current group is weak/single-frame.
            # 3. Existing group has stronger evidence.
            #
            if (
                distance == 1
                and len(
                    group["observations"]
                ) <= 1
                and existing_unique_frames >= 2
            ):

                print(
                    "Merging weak OCR variant "
                    f"{format_plate(plate)} "
                    "into "
                    f"{format_plate(existing_plate)}"
                )

                existing[
                    "observations"
                ].extend(
                    group["observations"]
                )

                merged = True

                break

        if not merged:

            final_groups.append(
                group
            )

    return final_groups


# ============================================================
# FINAL PLATE SELECTION
# ============================================================

def finalize_plate_groups(
    observations: list[dict[str, Any]]
) -> list[dict[str, Any]]:

    if not observations:
        return []

    merged_groups = merge_similar_plates(
        observations
    )

    final = []

    for group in merged_groups:

        plate = group[
            "plate"
        ]

        items = group[
            "observations"
        ]

        unique_frames = len(
            set(
                item["frame_index"]
                for item in items
            )
        )

        best = max(
            items,
            key=lambda x: (
                x["confidence"],
                x["quality"],
                x["detector_confidence"]
            )
        )

        # Strict confirmation.
        confirmed = (
            len(items) >= 2
            and unique_frames >= 2
        )

        final.append(
            {
                "plate": plate,
                "confirmed": confirmed,
                "observations": len(items),
                "unique_frames": unique_frames,
                "best": best
            }
        )

    final.sort(
        key=lambda x: (
            x["confirmed"],
            x["observations"],
            x["best"]["confidence"],
            x["best"]["quality"]
        ),
        reverse=True
    )

    return final


# ============================================================
# SAVE INDIVIDUAL EVIDENCE
# ============================================================

def save_plate_evidence(
    output_dir: Path,
    plate_number: int,
    plate_result: dict[str, Any],
    frames: dict[int, np.ndarray]
) -> dict[str, Any] | None:

    best = plate_result[
        "best"
    ]

    frame_index = best[
        "frame_index"
    ]

    frame = frames.get(
        frame_index
    )

    if frame is None:
        return None

    bbox = best[
        "bbox"
    ]

    crop = crop_from_box(
        frame,
        bbox
    )

    frame_path = (
        output_dir
        / f"plate_{plate_number}_best_frame.jpg"
    )

    crop_path = (
        output_dir
        / f"plate_{plate_number}_crop.jpg"
    )

    annotated_path = (
        output_dir
        / f"plate_{plate_number}_annotated.jpg"
    )

    cv2.imwrite(
        str(frame_path),
        frame
    )

    if crop is not None:

        cv2.imwrite(
            str(crop_path),
            crop
        )

    annotated = frame.copy()

    x1, y1, x2, y2 = bbox

    cv2.rectangle(
        annotated,
        (
            x1,
            y1
        ),
        (
            x2,
            y2
        ),
        (0, 255, 0),
        4
    )

    label = format_plate(
        plate_result["plate"]
    )

    cv2.putText(
        annotated,
        label,
        (
            x1,
            max(
                40,
                y1 - 12
            )
        ),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 0),
        3,
        cv2.LINE_AA
    )

    cv2.imwrite(
        str(annotated_path),
        annotated
    )

    return {
        "plate": label,
        "plate_compact": plate_result[
            "plate"
        ],
        "confirmed": plate_result[
            "confirmed"
        ],
        "best_frame": str(
            frame_path
        ),
        "plate_crop": str(
            crop_path
        ),
        "annotated_frame": str(
            annotated_path
        ),
        "timestamp": best[
            "timestamp"
        ]
    }


# ============================================================
# ANNOTATED VIDEO
# ============================================================

def create_annotated_video(
    video_path: Path,
    output_path: Path,
    all_detections: list[dict[str, Any]],
    final_plates: list[dict[str, Any]]
) -> bool:

    cap = cv2.VideoCapture(
        str(video_path)
    )

    if not cap.isOpened():
        return False

    fps = float(
        cap.get(
            cv2.CAP_PROP_FPS
        )
    )

    width = int(
        cap.get(
            cv2.CAP_PROP_FRAME_WIDTH
        )
    )

    height = int(
        cap.get(
            cv2.CAP_PROP_FRAME_HEIGHT
        )
    )

    if fps <= 0:
        fps = 30.0

    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(
            *"mp4v"
        ),
        fps,
        (
            width,
            height
        )
    )

    if not writer.isOpened():

        cap.release()

        return False

    # Only annotate sampled frames.
    detection_map = defaultdict(list)

    for detection in all_detections:

        detection_map[
            detection["frame_index"]
        ].append(
            detection
        )

    # Map best OCR observations to their frame.
    plate_by_frame = {}

    for plate in final_plates:

        best = plate.get(
            "best"
        )

        if best:

            plate_by_frame[
                best["frame_index"]
            ] = plate["plate"]

    frame_index = 0

    while True:

        success, frame = cap.read()

        if not success:
            break

        detections = detection_map.get(
            frame_index,
            []
        )

        for detection in detections:

            x1, y1, x2, y2 = detection[
                "bbox"
            ]

            label = "PLATE"

            if frame_index in plate_by_frame:

                label = format_plate(
                    plate_by_frame[
                        frame_index
                    ]
                )

            cv2.rectangle(
                frame,
                (
                    x1,
                    y1
                ),
                (
                    x2,
                    y2
                ),
                (0, 255, 0),
                3
            )

            cv2.putText(
                frame,
                label,
                (
                    x1,
                    max(
                        30,
                        y1 - 10
                    )
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
                cv2.LINE_AA
            )

        writer.write(
            frame
        )

        frame_index += 1

    writer.release()
    cap.release()

    return True


# ============================================================
# MAIN VIDEO PROCESSOR
# ============================================================

def process_video(
    video_path,
    output_dir,
    create_annotated_evidence_video: bool = False
):

    total_start = time.perf_counter()

    video_path = Path(
        video_path
    )

    output_dir = Path(
        output_dir
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    if not video_path.exists():

        return {
            "success": False,
            "confirmed": False,
            "plates": [],
            "message": (
                f"Video not found: "
                f"{video_path}"
            )
        }

    # ========================================================
    # TIMING: VIDEO INFORMATION
    # ========================================================

    info_start = time.perf_counter()

    info = get_video_info(
        video_path
    )

    info_time = (
        time.perf_counter()
        - info_start
    )

    fps = info[
        "fps"
    ]

    frame_count = info[
        "frame_count"
    ]

    width = info[
        "width"
    ]

    height = info[
        "height"
    ]

    duration = info[
        "duration_seconds"
    ]

    # ========================================================
    # ADAPTIVE SAMPLING
    # ========================================================

    sample_start = time.perf_counter()

    sample_indices = generate_sample_indices(
        frame_count,
        duration
    )

    frames = read_selected_frames(
        video_path,
        sample_indices
    )

    sample_time = (
        time.perf_counter()
        - sample_start
    )

    print()
    print("=" * 70)
    print("OPTIMIZED ADAPTIVE VIDEO ANPR")
    print("=" * 70)

    print(
        f"Video       : {video_path.name}"
    )

    print(
        f"Resolution  : "
        f"{width} x {height}"
    )

    print(
        f"FPS         : "
        f"{fps:.2f}"
    )

    print(
        f"Frames      : "
        f"{frame_count}"
    )

    print(
        f"Duration    : "
        f"{duration:.2f}s"
    )

    print(
        f"YOLO frames : "
        f"{len(sample_indices)}"
    )

    print(
        f"Frame indices: "
        f"{sample_indices}"
    )

    print(
        "Annotated video: "
        + (
            "enabled"
            if create_annotated_evidence_video
            else "disabled (individual evidence frames enabled)"
        )
    )

    # ========================================================
    # YOLO
    # ========================================================

    yolo_start = time.perf_counter()

    model = get_yolo_model()

    all_detections = []

    for frame_index in sample_indices:

        frame = frames.get(
            frame_index
        )

        if frame is None:
            continue

        detections = detect_plates_in_frame(
            model,
            frame,
            frame_index,
            fps
        )

        if detections:

            print(
                f"Frame {frame_index}: "
                f"{len(detections)} plate(s)"
            )

        all_detections.extend(
            detections
        )

    yolo_time = (
        time.perf_counter()
        - yolo_start
    )

    print()
    print(
        f"Raw YOLO detections: "
        f"{len(all_detections)}"
    )

    # ========================================================
    # GROUP REPEATED DETECTIONS
    # ========================================================

    grouping_start = time.perf_counter()

    groups = group_detections(
        all_detections,
        width,
        height
    )

    grouping_time = (
        time.perf_counter()
        - grouping_start
    )

    print(
        f"Physical plate groups: "
        f"{len(groups)}"
    )

    for number, group in enumerate(
        groups,
        start=1
    ):

        print(
            f"  Group {number}: "
            f"{len(group)} detections"
        )

    # ========================================================
    # OCR
    # ========================================================

    ocr_start = time.perf_counter()

    observations = []

    # Maximum number of groups investigated.
    #
    # This prevents a false-positive explosion if YOLO
    # produces many weak detections.
    groups = sorted(
        groups,
        key=lambda group: max(
            detection["quality"]
            for detection in group
        ),
        reverse=True
    )

    max_groups = min(
        6,
        len(groups)
    )

    groups_for_ocr = groups[
        :max_groups
    ]

    print()
    print(
        f"Groups selected for OCR: "
        f"{len(groups_for_ocr)}"
    )

    for group_number, group in enumerate(
        groups_for_ocr,
        start=1
    ):

        selected = select_best_group_detections(
            group
        )

        print()
        print(
            f"OCR group "
            f"{group_number}/"
            f"{len(groups_for_ocr)}"
        )

        print(
    "Frames selected: "
    + str(
        [
            d["frame_index"]
            for d in selected
        ]
    )
)

        for detection in selected:

            print(
                f"  OCR frame "
                f"{detection['frame_index']} "
                f"quality="
                f"{detection['quality']:.3f}"
            )

            ocr_results = ocr_plate_crop(
                detection["crop"]
            )

            for result in ocr_results:

                print(
                    f"      OCR text: "
                    f"{result['text']} "
                    f"confidence="
                    f"{result['confidence']:.3f}"
                )

                plate = normalize_plate(
                    result["text"]
                )

                if plate:

                    observations.append(
                        {
                            "plate": plate,
                            "text": result[
                                "text"
                            ],
                            "confidence": result[
                                "confidence"
                            ],
                            "variant": result[
                                "variant"
                            ],
                            "frame_index": detection[
                                "frame_index"
                            ],
                            "timestamp": detection[
                                "timestamp"
                            ],
                            "quality": detection[
                                "quality"
                            ],
                            "detector_confidence": detection[
                                "confidence"
                            ],
                            "bbox": detection[
                                "bbox"
                            ]
                        }
                    )

    ocr_time = (
        time.perf_counter()
        - ocr_start
    )

    # ========================================================
    # UNIQUE PLATE CONSENSUS
    # ========================================================

    consensus_start = time.perf_counter()

    final_plates = finalize_plate_groups(
        observations
    )

    consensus_time = (
        time.perf_counter()
        - consensus_start
    )

    print()
    print(
        f"Unique final plates: "
        f"{len(final_plates)}"
    )

    for plate in final_plates:

        print(
            f"  {format_plate(plate['plate'])} "
            f"| observations="
            f"{plate['observations']} "
            f"| frames="
            f"{plate['unique_frames']} "
            f"| confirmed="
            f"{plate['confirmed']}"
        )

    # ========================================================
    # EVIDENCE
    # ========================================================

    evidence_start = time.perf_counter()

    evidence_video = (
        output_dir
        / "evidence_video.mp4"
    )

    shutil.copy2(
        video_path,
        evidence_video
    )

    plate_evidence = []

    for number, plate_result in enumerate(
        final_plates,
        start=1
    ):

        evidence = save_plate_evidence(
            output_dir,
            number,
            plate_result,
            frames
        )

        if evidence:

            plate_evidence.append(
                evidence
            )

    annotated_video = (
        output_dir
        / "annotated_evidence_video.mp4"
    )

    # Full annotated-video encoding requires decoding and re-encoding
    # every frame. That was the largest non-ANPR bottleneck (~14 s in
    # the previous test). It is therefore optional and disabled by
    # default. Individual annotated evidence frames are still generated.
    annotated_created = False

    if create_annotated_evidence_video:
        annotated_created = create_annotated_video(
            video_path,
            annotated_video,
            all_detections,
            final_plates
        )

    evidence_time = (
        time.perf_counter()
        - evidence_start
    )

    # ========================================================
    # TOTAL TIME
    # ========================================================

    total_time = (
        time.perf_counter()
        - total_start
    )

    # ========================================================
    # RESULT
    # ========================================================

    result = {
        "success": (
            len(final_plates) > 0
        ),

        "confirmed": any(
            plate["confirmed"]
            for plate in final_plates
        ),

        "plates": [
            {
                "plate": format_plate(
                    plate["plate"]
                ),
                "plate_compact": plate[
                    "plate"
                ],
                "confirmed": plate[
                    "confirmed"
                ],
                "ocr_observations": plate[
                    "observations"
                ],
                "unique_frames": plate[
                    "unique_frames"
                ],
                "timestamp": plate[
                    "best"
                ]["timestamp"],
                "frame_index": plate[
                    "best"
                ]["frame_index"],
                "ocr_confidence": plate[
                    "best"
                ]["confidence"],
                "detector_confidence": plate[
                    "best"
                ]["detector_confidence"]
            }
            for plate in final_plates
        ],

        "video": {
            **info,

            "adaptive_sampling": {
                "yolo_frames": len(
                    sample_indices
                ),
                "sample_indices": sample_indices
            },

            "raw_yolo_detections": len(
                all_detections
            ),

            "physical_plate_groups": len(
                groups
            ),

            "ocr_groups": len(
                groups_for_ocr
            ),

            "valid_ocr_observations": len(
                observations
            )
        },

        "timing": {
            "video_info_seconds": round(
                info_time,
                3
            ),

            "sampling_seconds": round(
                sample_time,
                3
            ),

            "yolo_seconds": round(
                yolo_time,
                3
            ),

            "grouping_seconds": round(
                grouping_time,
                3
            ),

            "ocr_seconds": round(
                ocr_time,
                3
            ),

            "consensus_seconds": round(
                consensus_time,
                3
            ),

            "evidence_seconds": round(
                evidence_time,
                3
            ),

            "total_processing_seconds": round(
                total_time,
                3
            )
        },

        "processing_time_seconds": round(
            total_time,
            3
        ),

        "evidence": {
            "original_video": str(
                evidence_video
            ),

            "annotated_video": (
                str(annotated_video)
                if annotated_created
                else None
            ),

            "annotated_video_generated": bool(
                annotated_created
            ),

            "annotated_video_requested": bool(
                create_annotated_evidence_video
            ),

            "plates": plate_evidence
        }
    }

    # ========================================================
    # SAVE JSON
    # ========================================================

    result_path = (
        output_dir
        / "result.json"
    )

    result["result_json"] = str(
        result_path
    )

    with open(
        result_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            indent=2
        )

    # ========================================================
    # PRINT SUMMARY
    # ========================================================

    print()
    print("=" * 70)
    print("FINAL ANPR RESULT")
    print("=" * 70)

    if final_plates:

        for plate in final_plates:

            print(
                f"{format_plate(plate['plate'])}"
                f" | confirmed="
                f"{plate['confirmed']}"
                f" | observations="
                f"{plate['observations']}"
                f" | unique_frames="
                f"{plate['unique_frames']}"
            )

    else:

        print(
            "No valid registration number "
            "could be confirmed."
        )

    print()
    print(
        "TIMING"
    )

    print(
        f"YOLO             : "
        f"{yolo_time:.3f}s"
    )

    print(
        f"OCR              : "
        f"{ocr_time:.3f}s"
    )

    print(
        f"Grouping         : "
        f"{grouping_time:.3f}s"
    )

    print(
        f"Evidence         : "
        f"{evidence_time:.3f}s"
    )

    print(
        f"TOTAL            : "
        f"{total_time:.3f}s"
    )

    print("=" * 70)

    return result