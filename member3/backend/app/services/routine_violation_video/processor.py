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
# INDIAN PLATE VALIDATION
# ============================================================

INDIAN_STATE_CODES = {
    "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL",
    "DN", "GA", "GJ", "HR", "HP", "JK", "JH", "KA", "KL",
    "LA", "LD", "MH", "ML", "MN", "MP", "MZ", "NL", "OD",
    "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK",
    "UP", "WB"
}


def clean_ocr_text(text: str) -> str:

    if not text:
        return ""

    text = str(text).upper()

    text = re.sub(
        r"[^A-Z0-9]",
        "",
        text,
    )

    return text


def normalize_alpha(text: str) -> str:

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
        mapping.get(ch, ch)
        for ch in text
    )


def normalize_numeric(text: str) -> str:

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
        mapping.get(ch, ch)
        for ch in text
    )


def normalize_plate(text: str) -> str | None:

    text = clean_ocr_text(text)

    if len(text) != 10:
        return None

    state = normalize_alpha(
        text[:2]
    )

    district = normalize_numeric(
        text[2:4]
    )

    series = normalize_alpha(
        text[4:6]
    )

    number = normalize_numeric(
        text[6:10]
    )

    if state not in INDIAN_STATE_CODES:
        return None

    if not district.isdigit():
        return None

    if not re.fullmatch(
        r"[A-Z]{2}",
        series,
    ):
        return None

    if not number.isdigit():
        return None

    plate = (
        state
        + district
        + series
        + number
    )

    return plate


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

def get_video_info(video_path: Path):

    cap = cv2.VideoCapture(
        str(video_path)
    )

    if not cap.isOpened():
        raise RuntimeError(
            f"Could not open video: {video_path}"
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
# FRAME SAMPLING
# ============================================================

def make_sample_indices(
    frame_count: int,
    duration: float,
):

    if frame_count <= 0:
        return []

    # More temporal coverage for short videos.
    if duration <= 6:
        target = 24

    elif duration <= 10:
        target = 28

    elif duration <= 20:
        target = 36

    elif duration <= 30:
        target = 45

    else:
        target = min(
            60,
            max(
                45,
                int(duration * 1.5),
            ),
        )

    target = min(
        target,
        frame_count,
    )

    indices = np.linspace(
        0,
        frame_count - 1,
        target,
        dtype=np.int32,
    )

    return sorted(
        set(
            int(x)
            for x in indices
        )
    )


# ============================================================
# FRAME READER
# ============================================================

def read_frames(
    video_path: Path,
    indices: list[int],
):

    requested = sorted(
        set(indices)
    )

    frames = {}

    if not requested:
        return frames

    cap = cv2.VideoCapture(
        str(video_path)
    )

    if not cap.isOpened():
        return frames

    current_target = -1

    for index in requested:

        if index < current_target:
            continue

        cap.set(
            cv2.CAP_PROP_POS_FRAMES,
            index,
        )

        ok, frame = cap.read()

        if ok and frame is not None:
            frames[index] = frame

        current_target = index

    cap.release()

    return frames


# ============================================================
# IMAGE QUALITY
# ============================================================

def calculate_sharpness(
    image: np.ndarray,
) -> float:

    if image is None or image.size == 0:
        return 0.0

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY,
    )

    return float(
        cv2.Laplacian(
            gray,
            cv2.CV_64F,
        ).var()
    )


def calculate_brightness(
    image: np.ndarray,
) -> float:

    if image is None or image.size == 0:
        return 0.0

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY,
    )

    return float(
        np.mean(gray)
    )


def plate_quality(
    crop: np.ndarray,
    detector_confidence: float,
    frame_width: int,
    frame_height: int,
):

    if crop is None or crop.size == 0:
        return 0.0

    h, w = crop.shape[:2]

    area_ratio = (
        (w * h)
        / max(
            1,
            frame_width * frame_height,
        )
    )

    aspect_ratio = (
        w / max(1, h)
    )

    sharpness = calculate_sharpness(
        crop
    )

    brightness = calculate_brightness(
        crop
    )

    # Plate aspect-ratio score.
    if 2.0 <= aspect_ratio <= 6.0:
        aspect_score = 1.0

    elif 1.5 <= aspect_ratio <= 7.0:
        aspect_score = 0.7

    else:
        aspect_score = 0.3

    sharpness_score = (
        1.0
        - math.exp(
            -sharpness / 120.0
        )
    )

    area_score = min(
        1.0,
        math.sqrt(
            area_ratio / 0.02
        ),
    )

    if 40 <= brightness <= 225:
        brightness_score = 1.0

    elif 25 <= brightness <= 240:
        brightness_score = 0.65

    else:
        brightness_score = 0.3

    score = (
        0.35 * detector_confidence
        + 0.25 * sharpness_score
        + 0.15 * area_score
        + 0.15 * aspect_score
        + 0.10 * brightness_score
    )

    return float(score)


# ============================================================
# BOX / CROP
# ============================================================

def expand_box(
    box,
    width,
    height,
    padding=0.08,
):

    x1, y1, x2, y2 = box

    bw = x2 - x1
    bh = y2 - y1

    px = int(
        bw * padding
    )

    py = int(
        bh * padding
    )

    x1 = max(
        0,
        x1 - px,
    )

    y1 = max(
        0,
        y1 - py,
    )

    x2 = min(
        width - 1,
        x2 + px,
    )

    y2 = min(
        height - 1,
        y2 + py,
    )

    return (
        x1,
        y1,
        x2,
        y2,
    )


def extract_crop(
    frame,
    box,
):

    h, w = frame.shape[:2]

    x1, y1, x2, y2 = expand_box(
        box,
        w,
        h,
    )

    if x2 <= x1 or y2 <= y1:
        return None

    crop = frame[
        y1:y2,
        x1:x2,
    ]

    if crop.size == 0:
        return None

    return crop.copy()


# ============================================================
# YOLO DETECTION
# ============================================================

def detect_plates(
    model,
    frame,
    frame_index,
    fps,
):

    height, width = frame.shape[:2]

    results = model.predict(
        source=frame,

        # Keep spatial resolution high.
        imgsz=1280,

        # Lower threshold than before so weak,
        # clearly visible plates are not discarded.
        conf=0.05,

        max_det=50,

        save=False,

        verbose=False,

        device="cpu",
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

            xyxy = (
                result.boxes.xyxy[
                    i
                ]
                .cpu()
                .numpy()
            )

            x1, y1, x2, y2 = [
                int(round(float(v)))
                for v in xyxy
            ]

            x1 = max(
                0,
                min(width - 1, x1),
            )

            y1 = max(
                0,
                min(height - 1, y1),
            )

            x2 = max(
                0,
                min(width - 1, x2),
            )

            y2 = max(
                0,
                min(height - 1, y2),
            )

            if x2 <= x1 or y2 <= y1:
                continue

            crop = extract_crop(
                frame,
                (
                    x1,
                    y1,
                    x2,
                    y2,
                ),
            )

            if crop is None:
                continue

            quality = plate_quality(
                crop,
                confidence,
                width,
                height,
            )

            detections.append(
                {
                    "frame_index": frame_index,
                    "timestamp": (
                        frame_index / fps
                    ),
                    "bbox": [
                        x1,
                        y1,
                        x2,
                        y2,
                    ],
                    "confidence": confidence,
                    "quality": quality,
                    "sharpness": calculate_sharpness(
                        crop
                    ),
                    "crop": crop,
                }
            )

    return detections


# ============================================================
# SPATIAL ASSOCIATION
# ============================================================

def box_center(box):

    x1, y1, x2, y2 = box

    return (
        (x1 + x2) / 2.0,
        (y1 + y2) / 2.0,
    )


def box_iou(
    box_a,
    box_b,
):

    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    ix1 = max(
        ax1,
        bx1,
    )

    iy1 = max(
        ay1,
        by1,
    )

    ix2 = min(
        ax2,
        bx2,
    )

    iy2 = min(
        ay2,
        by2,
    )

    iw = max(
        0,
        ix2 - ix1,
    )

    ih = max(
        0,
        iy2 - iy1,
    )

    intersection = (
        iw * ih
    )

    area_a = max(
        0,
        ax2 - ax1,
    ) * max(
        0,
        ay2 - ay1,
    )

    area_b = max(
        0,
        bx2 - bx1,
    ) * max(
        0,
        by2 - by1,
    )

    union = (
        area_a
        + area_b
        - intersection
    )

    if union <= 0:
        return 0.0

    return (
        intersection / union
    )


def detection_distance(
    detection,
    track,
    frame_width,
    frame_height,
):

    cx1, cy1 = box_center(
        detection["bbox"]
    )

    cx2, cy2 = box_center(
        track["last_bbox"]
    )

    dx = (
        cx1 - cx2
    ) / max(
        1,
        frame_width,
    )

    dy = (
        cy1 - cy2
    ) / max(
        1,
        frame_height,
    )

    return math.sqrt(
        dx * dx
        + dy * dy
    )


# ============================================================
# MULTI-PLATE TRACKING
# ============================================================

def build_plate_tracks(
    detections,
    frame_width,
    frame_height,
):

    tracks = []

    next_track_id = 1

    detections = sorted(
        detections,
        key=lambda d: (
            d["frame_index"],
            -d["quality"],
        ),
    )

    for detection in detections:

        best_track = None
        best_distance = float("inf")

        for track in tracks:

            frame_gap = (
                detection["frame_index"]
                - track["last_frame"]
            )

            # Don't associate detections too far apart.
            if frame_gap > 12:
                continue

            distance = detection_distance(
                detection,
                track,
                frame_width,
                frame_height,
            )

            iou = box_iou(
                detection["bbox"],
                track["last_bbox"],
            )

            # Either overlapping boxes or nearby centers.
            if (
                iou >= 0.10
                or distance <= 0.08
            ):

                if distance < best_distance:
                    best_distance = distance
                    best_track = track

        if best_track is None:

            track = {
                "track_id": next_track_id,
                "detections": [
                    detection
                ],
                "last_frame": detection[
                    "frame_index"
                ],
                "last_bbox": detection[
                    "bbox"
                ],
            }

            tracks.append(track)

            next_track_id += 1

        else:

            best_track[
                "detections"
            ].append(
                detection
            )

            best_track[
                "last_frame"
            ] = detection[
                "frame_index"
            ]

            best_track[
                "last_bbox"
            ] = detection[
                "bbox"
            ]

    return tracks


# ============================================================
# OCR PREPROCESSING
# ============================================================

def upscale_crop(
    crop,
):

    if crop is None or crop.size == 0:
        return crop

    h, w = crop.shape[:2]

    target_height = 180

    scale = max(
        2.0,
        target_height / max(
            1,
            h,
        ),
    )

    new_width = max(
        1,
        int(w * scale),
    )

    new_height = max(
        1,
        int(h * scale),
    )

    return cv2.resize(
        crop,
        (
            new_width,
            new_height,
        ),
        interpolation=cv2.INTER_CUBIC,
    )


def preprocess_primary(
    crop,
):

    image = upscale_crop(
        crop
    )

    lab = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2LAB,
    )

    l, a, b = cv2.split(
        lab
    )

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8),
    )

    l = clahe.apply(l)

    enhanced = cv2.merge(
        (l, a, b)
    )

    return cv2.cvtColor(
        enhanced,
        cv2.COLOR_LAB2BGR,
    )


def preprocess_sharpened(
    crop,
):

    image = preprocess_primary(
        crop
    )

    blur = cv2.GaussianBlur(
        image,
        (0, 0),
        1.2,
    )

    return cv2.addWeighted(
        image,
        1.6,
        blur,
        -0.6,
        0,
    )


def preprocess_thresholded(
    crop,
):

    image = upscale_crop(
        crop
    )

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY,
    )

    clahe = cv2.createCLAHE(
        clipLimit=2.5,
        tileGridSize=(8, 8),
    )

    gray = clahe.apply(
        gray
    )

    thresholded = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        7,
    )

    return cv2.cvtColor(
        thresholded,
        cv2.COLOR_GRAY2BGR,
    )


# ============================================================
# RAPIDOCR
# ============================================================

def run_ocr(
    image,
):

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
                "confidence": confidence,
            }
        )

    return observations


def ocr_crop(
    crop,
):

    all_results = []

    variants = [
        (
            "primary",
            preprocess_primary(
                crop
            ),
        ),
        (
            "sharpened",
            preprocess_sharpened(
                crop
            ),
        ),
        (
            "thresholded",
            preprocess_thresholded(
                crop
            ),
        ),
    ]

    for variant_name, image in variants:

        print(
            f"    RapidOCR: {variant_name}"
        )

        results = run_ocr(
            image
        )

        for result in results:

            all_results.append(
                {
                    **result,
                    "variant": variant_name,
                }
            )

        # If we already have a valid plate,
        # don't waste more CPU on variants.
        valid = False

        for result in results:

            if normalize_plate(
                result["text"]
            ):

                valid = True
                break

        if valid:
            break

    return all_results


# ============================================================
# TRACK OCR CONSENSUS
# ============================================================

def select_track_plate(
    observations,
):

    valid = []

    for item in observations:

        plate = normalize_plate(
            item["text"]
        )

        if plate:

            valid.append(
                {
                    **item,
                    "plate": plate,
                }
            )

    if not valid:
        return None

    grouped = defaultdict(
        list
    )

    for item in valid:

        grouped[
            item["plate"]
        ].append(
            item
        )

    ranked = sorted(
        grouped.items(),
        key=lambda pair: (
            len(pair[1]),
            max(
                x["confidence"]
                for x in pair[1]
            ),
        ),
        reverse=True,
    )

    best_plate, items = ranked[0]

    unique_frames = len(
        set(
            x["frame_index"]
            for x in items
        )
    )

    best = max(
        items,
        key=lambda x: (
            x["confidence"],
            x["quality"],
        ),
    )

    # Strict multi-frame confirmation.
    confirmed = (
        len(items) >= 2
        and unique_frames >= 2
    )

    return {
        "plate": best_plate,
        "count": len(items),
        "unique_frames": unique_frames,
        "confirmed": confirmed,
        "best": best,
        "observations": valid,
    }


# ============================================================
# ANNOTATED VIDEO
# ============================================================

def create_annotated_video(
    video_path,
    output_path,
    track_results,
):

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

    # MP4 writer.
    fourcc = cv2.VideoWriter_fourcc(
        *"mp4v"
    )

    writer = cv2.VideoWriter(
        str(output_path),
        fourcc,
        fps,
        (
            width,
            height,
        ),
    )

    if not writer.isOpened():
        cap.release()
        return False

    # --------------------------------------------------------
    # Convert track detections into frame lookup.
    # --------------------------------------------------------

    frame_annotations = defaultdict(
        list
    )

    for track in track_results:

        for detection in track[
            "detections"
        ]:

            frame_annotations[
                detection[
                    "frame_index"
                ]
            ].append(
                {
                    "bbox": detection[
                        "bbox"
                    ],
                    "track_id": track[
                        "track_id"
                    ],
                    "plate": track.get(
                        "plate"
                    ),
                    "confirmed": track.get(
                        "confirmed",
                        False,
                    ),
                }
            )

    frame_index = 0

    while True:

        ok, frame = cap.read()

        if not ok:
            break

        annotations = frame_annotations.get(
            frame_index,
            [],
        )

        for annotation in annotations:

            x1, y1, x2, y2 = annotation[
                "bbox"
            ]

            plate = annotation[
                "plate"
            ]

            track_id = annotation[
                "track_id"
            ]

            if plate:

                label = (
                    f"V{track_id}: "
                    f"{format_plate(plate)}"
                )

            else:

                label = (
                    f"V{track_id}: "
                    "PLATE"
                )

            cv2.rectangle(
                frame,
                (
                    x1,
                    y1,
                ),
                (
                    x2,
                    y2,
                ),
                (0, 255, 0),
                3,
            )

            cv2.putText(
                frame,
                label,
                (
                    x1,
                    max(
                        30,
                        y1 - 10,
                    ),
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

        writer.write(
            frame
        )

        frame_index += 1

    writer.release()
    cap.release()

    return True


# ============================================================
# MAIN PROCESSOR
# ============================================================

def process_video(
    video_path,
    output_dir,
):

    start_time = time.perf_counter()

    video_path = Path(
        video_path
    )

    output_dir = Path(
        output_dir
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not video_path.exists():

        return {
            "success": False,
            "confirmed": False,
            "plates": [],
            "message": (
                f"Video not found: "
                f"{video_path}"
            ),
        }

    info = get_video_info(
        video_path
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

    print()
    print("=" * 70)
    print("MULTI-VEHICLE VIDEO ANPR")
    print("=" * 70)

    print(
        f"Resolution : "
        f"{width} x {height}"
    )

    print(
        f"FPS        : "
        f"{fps:.2f}"
    )

    print(
        f"Frames     : "
        f"{frame_count}"
    )

    print(
        f"Duration   : "
        f"{duration:.2f}s"
    )

    # --------------------------------------------------------
    # SAMPLE VIDEO
    # --------------------------------------------------------

    sample_indices = make_sample_indices(
        frame_count,
        duration,
    )

    print()
    print(
        f"Sampling "
        f"{len(sample_indices)} frames..."
    )

    frames = read_frames(
        video_path,
        sample_indices,
    )

    # --------------------------------------------------------
    # YOLO
    # --------------------------------------------------------

    model = get_yolo_model()

    all_detections = []

    for frame_index in sample_indices:

        frame = frames.get(
            frame_index
        )

        if frame is None:
            continue

        detections = detect_plates(
            model,
            frame,
            frame_index,
            fps,
        )

        if detections:

            print(
                f"Frame "
                f"{frame_index}: "
                f"{len(detections)} "
                f"plate(s)"
            )

        all_detections.extend(
            detections
        )

    print()
    print(
        f"Total raw detections: "
        f"{len(all_detections)}"
    )

    # --------------------------------------------------------
    # MULTI-PLATE TRACKS
    # --------------------------------------------------------

    tracks = build_plate_tracks(
        all_detections,
        width,
        height,
    )

    print(
        f"Detected plate tracks: "
        f"{len(tracks)}"
    )

    # --------------------------------------------------------
    # REMOVE VERY WEAK SINGLETONS
    # --------------------------------------------------------

    useful_tracks = []

    for track in tracks:

        detections = track[
            "detections"
        ]

        best_detection = max(
            detections,
            key=lambda d: (
                d["quality"],
                d["confidence"],
            ),
        )

        # Keep a track if:
        # - it appears multiple times, OR
        # - its best detection is strong.
        if (
            len(detections) >= 2
            or best_detection[
                "confidence"
            ] >= 0.30
        ):

            useful_tracks.append(
                track
            )

    print(
        f"Useful plate tracks: "
        f"{len(useful_tracks)}"
    )

    # --------------------------------------------------------
    # OCR EACH VEHICLE
    # --------------------------------------------------------

    final_tracks = []

    for track in useful_tracks:

        track_id = track[
            "track_id"
        ]

        detections = sorted(
            track[
                "detections"
            ],
            key=lambda d: (
                d["quality"],
                d["confidence"],
                d["sharpness"],
            ),
            reverse=True,
        )

        # OCR several strong temporal observations
        # for THIS vehicle independently.
        ocr_detections = detections[
            :4
        ]

        print()
        print(
            f"Vehicle track V{track_id}"
        )

        observations = []

        for detection in ocr_detections:

            frame_index = detection[
                "frame_index"
            ]

            print(
                f"  OCR frame "
                f"{frame_index}"
            )

            ocr_results = ocr_crop(
                detection[
                    "crop"
                ]
            )

            for result in ocr_results:

                observations.append(
                    {
                        **result,
                        "frame_index": frame_index,
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
                        ],
                    }
                )

                print(
                    f"    "
                    f"{result['text']} "
                    f"conf="
                    f"{result['confidence']:.3f}"
                )

        consensus = select_track_plate(
            observations
        )

        if consensus:

            plate = consensus[
                "plate"
            ]

            confirmed = consensus[
                "confirmed"
            ]

            best = consensus[
                "best"
            ]

            print(
                f"  RESULT: "
                f"{format_plate(plate)}"
            )

            print(
                f"  OCR observations: "
                f"{consensus['count']}"
            )

            print(
                f"  Unique frames: "
                f"{consensus['unique_frames']}"
            )

        else:

            plate = None
            confirmed = False
            best = None

            print(
                "  OCR could not "
                "confirm this plate."
            )

        track_result = {
            "track_id": track_id,
            "plate": plate,
            "confirmed": confirmed,
            "detections": detections,
            "ocr_observations": observations,
        }

        if best:

            track_result[
                "best_frame_index"
            ] = best[
                "frame_index"
            ]

            track_result[
                "best_timestamp"
            ] = best[
                "timestamp"
            ]

            track_result[
                "best_bbox"
            ] = best[
                "bbox"
            ]

            track_result[
                "ocr_confidence"
            ] = best[
                "confidence"
            ]

            track_result[
                "detector_confidence"
            ] = best[
                "detector_confidence"
            ]

        final_tracks.append(
            track_result
        )

    # --------------------------------------------------------
    # SAVE BEST FRAME/CROP FOR EACH VEHICLE
    # --------------------------------------------------------

    evidence = []

    for track in final_tracks:

        track_id = track[
            "track_id"
        ]

        frame_index = track.get(
            "best_frame_index"
        )

        if frame_index is None:
            # Use strongest detection if OCR failed.
            frame_index = max(
                track["detections"],
                key=lambda d: d[
                    "quality"
                ],
            )[
                "frame_index"
            ]

        frame = frames.get(
            frame_index
        )

        if frame is None:

            extra = read_frames(
                video_path,
                [frame_index],
            )

            frame = extra.get(
                frame_index
            )

        if frame is None:
            continue

        bbox = track.get(
            "best_bbox"
        )

        if bbox is None:

            best_detection = max(
                track[
                    "detections"
                ],
                key=lambda d: d[
                    "quality"
                ],
            )

            bbox = best_detection[
                "bbox"
            ]

        crop = extract_crop(
            frame,
            bbox,
        )

        frame_path = (
            output_dir
            / f"vehicle_{track_id}_best_frame.jpg"
        )

        plate_path = (
            output_dir
            / f"vehicle_{track_id}_plate.jpg"
        )

        annotated_path = (
            output_dir
            / f"vehicle_{track_id}_annotated.jpg"
        )

        cv2.imwrite(
            str(frame_path),
            frame,
        )

        if crop is not None:

            cv2.imwrite(
                str(plate_path),
                crop,
            )

        annotated = frame.copy()

        x1, y1, x2, y2 = bbox

        cv2.rectangle(
            annotated,
            (
                x1,
                y1,
            ),
            (
                x2,
                y2,
            ),
            (0, 255, 0),
            4,
        )

        plate = track.get(
            "plate"
        )

        label = (
            format_plate(plate)
            if plate
            else "PLATE DETECTED"
        )

        cv2.putText(
            annotated,
            f"V{track_id}: {label}",
            (
                x1,
                max(
                    40,
                    y1 - 12,
                ),
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0),
            3,
            cv2.LINE_AA,
        )

        cv2.imwrite(
            str(annotated_path),
            annotated,
        )

        evidence.append(
            {
                "track_id": track_id,
                "plate": format_plate(
                    track.get(
                        "plate"
                    )
                ),
                "best_frame": str(
                    frame_path
                ),
                "best_plate": str(
                    plate_path
                ),
                "annotated_frame": str(
                    annotated_path
                ),
            }
        )

    # --------------------------------------------------------
    # ANNOTATED FULL VIDEO
    # --------------------------------------------------------

    annotated_video = (
        output_dir
        / "annotated_evidence_video.mp4"
    )

    print()
    print(
        "Creating annotated evidence video..."
    )

    video_created = create_annotated_video(
        video_path,
        annotated_video,
        final_tracks,
    )

    # Original evidence copy.
    evidence_video = (
        output_dir
        / "evidence_video.mp4"
    )

    shutil.copy2(
        video_path,
        evidence_video,
    )

    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    confirmed_plates = [
        track
        for track in final_tracks
        if track.get(
            "confirmed"
        )
        and track.get(
            "plate"
        )
    ]

    processing_time = (
        time.perf_counter()
        - start_time
    )

    result = {
        "success": len(
            final_tracks
        ) > 0,

        "confirmed": len(
            confirmed_plates
        ) > 0,

        "plates": [
            {
                "vehicle_id": (
                    f"V{track['track_id']}"
                ),
                "plate": format_plate(
                    track.get(
                        "plate"
                    )
                ),
                "plate_compact": track.get(
                    "plate"
                ),
                "confirmed": track.get(
                    "confirmed",
                    False,
                ),
                "ocr_confidence": track.get(
                    "ocr_confidence"
                ),
                "detector_confidence": track.get(
                    "detector_confidence"
                ),
                "best_frame_index": track.get(
                    "best_frame_index"
                ),
                "timestamp": track.get(
                    "best_timestamp"
                ),
            }
            for track in final_tracks
        ],

        "video": {
            **info,
            "sampled_frames": len(
                sample_indices
            ),
            "raw_plate_detections": len(
                all_detections
            ),
            "plate_tracks": len(
                final_tracks
            ),
        },

        "processing_time_seconds": round(
            processing_time,
            3,
        ),

        "evidence": {
            "original_video": str(
                evidence_video
            ),
            "annotated_video": (
                str(
                    annotated_video
                )
                if video_created
                else None
            ),
            "vehicles": evidence,
        },
    }

    result_json = (
        output_dir
        / "result.json"
    )

    with open(
        result_json,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            result,
            f,
            indent=2,
        )

    result[
        "result_json"
    ] = str(
        result_json
    )

    print()
    print("=" * 70)
    print("FINAL MULTI-VEHICLE RESULT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    print("=" * 70)

    return result