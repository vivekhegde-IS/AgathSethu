from pathlib import Path
import re

import cv2
from ultralytics import YOLO
from rapidocr_onnxruntime import RapidOCR


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = (
    BASE_DIR
    / "models"
    / "number_plate"
    / "number_plate_detector.pt"
)

IMAGE_PATH = BASE_DIR / "test_plate.png"

CROP_PATH = BASE_DIR / "detected_plate_crop.png"

PADDED_CROP_PATH = (
    BASE_DIR / "detected_plate_crop_padded.png"
)


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):
    if not text:
        return ""

    text = str(text).upper()

    return re.sub(
        r"[^A-Z0-9]",
        "",
        text
    )


# ============================================================
# INDIAN STATE / UT CODES
# ============================================================

INDIAN_STATE_CODES = {
    "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL",
    "DN", "GA", "GJ", "HP", "HR", "JH", "JK", "KA", "KL",
    "LA", "LD", "MH", "ML", "MN", "MP", "MZ", "NL", "OD",
    "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK", "UP",
    "WB"
}


# ============================================================
# PLATE FORMAT CHECK
# ============================================================

def looks_like_indian_plate(text):
    """
    Basic Indian registration plate structure.

    Expected compact form:

        SSNNAAAANNNN

    More generally:

        SS + 1/2 digits + 1-3 letters + 3/4 digits
    """

    text = normalize_text(text)

    pattern = (
        r"^([A-Z]{2})"
        r"([0-9]{1,2})"
        r"([A-Z]{1,3})"
        r"([0-9]{3,4})$"
    )

    match = re.match(
        pattern,
        text
    )

    if not match:
        return False

    state = match.group(1)

    return state in INDIAN_STATE_CODES


# ============================================================
# CROP WITH PADDING
# ============================================================

def crop_with_padding(
    image,
    x1,
    y1,
    x2,
    y2,
    padding_ratio=0.15
):
    """
    Expand the YOLO plate bounding box so characters near
    the plate boundary are not clipped.
    """

    image_height, image_width = image.shape[:2]

    box_width = x2 - x1
    box_height = y2 - y1

    pad_x = int(
        box_width * padding_ratio
    )

    pad_y = int(
        box_height * padding_ratio
    )

    new_x1 = max(
        0,
        x1 - pad_x
    )

    new_y1 = max(
        0,
        y1 - pad_y
    )

    new_x2 = min(
        image_width,
        x2 + pad_x
    )

    new_y2 = min(
        image_height,
        y2 + pad_y
    )

    return image[
        new_y1:new_y2,
        new_x1:new_x2
    ]


# ============================================================
# OCR PREPROCESSING
# ============================================================

def create_variants(crop):

    variants = []

    # --------------------------------------------------------
    # Variant 1: enlarged color image
    # --------------------------------------------------------

    enlarged = cv2.resize(
        crop,
        None,
        fx=3.0,
        fy=3.0,
        interpolation=cv2.INTER_CUBIC
    )

    variants.append(
        (
            "enlarged",
            enlarged
        )
    )

    # --------------------------------------------------------
    # Grayscale
    # --------------------------------------------------------

    gray = cv2.cvtColor(
        enlarged,
        cv2.COLOR_BGR2GRAY
    )

    variants.append(
        (
            "grayscale",
            gray
        )
    )

    # --------------------------------------------------------
    # CLAHE contrast enhancement
    # --------------------------------------------------------

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    )

    enhanced = clahe.apply(
        gray
    )

    variants.append(
        (
            "clahe",
            enhanced
        )
    )

    # --------------------------------------------------------
    # Sharpened
    # --------------------------------------------------------

    blurred = cv2.GaussianBlur(
        enhanced,
        (0, 0),
        1.0
    )

    sharpened = cv2.addWeighted(
        enhanced,
        1.5,
        blurred,
        -0.5,
        0
    )

    variants.append(
        (
            "sharpened",
            sharpened
        )
    )

    # --------------------------------------------------------
    # Adaptive threshold
    # --------------------------------------------------------

    thresholded = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11
    )

    variants.append(
        (
            "thresholded",
            thresholded
        )
    )

    # --------------------------------------------------------
    # Otsu threshold
    # --------------------------------------------------------

    _, otsu = cv2.threshold(
        enhanced,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    variants.append(
        (
            "otsu",
            otsu
        )
    )

    return variants


# ============================================================
# LOAD MODELS
# ============================================================

print("================================")
print("NUMBER PLATE OCR TEST")
print("================================")

print()
print("Model:")
print(MODEL_PATH)

print()
print("Image:")
print(IMAGE_PATH)


if not MODEL_PATH.exists():

    raise FileNotFoundError(
        f"Model not found:\n{MODEL_PATH}"
    )


if not IMAGE_PATH.exists():

    raise FileNotFoundError(
        f"Image not found:\n{IMAGE_PATH}"
    )


print()
print("Loading YOLO model...")

model = YOLO(
    str(MODEL_PATH)
)

print("YOLO loaded successfully.")


print()
print("Loading RapidOCR...")

ocr = RapidOCR()

print("RapidOCR loaded successfully.")


# ============================================================
# READ IMAGE
# ============================================================

print()
print("Reading image...")

frame = cv2.imread(
    str(IMAGE_PATH)
)

if frame is None:

    raise RuntimeError(
        "Could not read test image."
    )


print(
    "Image resolution:",
    frame.shape[1],
    "x",
    frame.shape[0]
)


# ============================================================
# YOLO
# ============================================================

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


# ============================================================
# COLLECT DETECTIONS
# ============================================================

candidates = []


for result in results:

    if result.boxes is None:
        continue

    for box in result.boxes:

        confidence = float(
            box.conf[0]
        )

        x1, y1, x2, y2 = map(
            int,
            box.xyxy[0].tolist()
        )

        x1 = max(
            0,
            x1
        )

        y1 = max(
            0,
            y1
        )

        x2 = min(
            frame.shape[1],
            x2
        )

        y2 = min(
            frame.shape[0],
            y2
        )

        if x2 <= x1 or y2 <= y1:
            continue

        crop = frame[
            y1:y2,
            x1:x2
        ]

        if crop.size == 0:
            continue

        area = (
            (x2 - x1)
            *
            (y2 - y1)
        )

        candidates.append(
            {
                "confidence": confidence,
                "area": area,
                "bbox": [
                    x1,
                    y1,
                    x2,
                    y2
                ],
                "crop": crop
            }
        )


print()
print(
    "Total plates detected:",
    len(candidates)
)


if not candidates:

    print("NO PLATE DETECTED")

    raise SystemExit(1)


# ============================================================
# SELECT BEST DETECTION
# ============================================================

candidates.sort(
    key=lambda item: (
        item["confidence"],
        item["area"]
    ),
    reverse=True
)

best = candidates[0]

x1, y1, x2, y2 = best["bbox"]


print()
print("================================")
print("BEST PLATE DETECTION")
print("================================")

print(
    "YOLO confidence:",
    round(
        best["confidence"],
        4
    )
)

print(
    "Original bounding box:",
    best["bbox"]
)


# ============================================================
# SAVE ORIGINAL CROP
# ============================================================

original_crop = best["crop"]

cv2.imwrite(
    str(CROP_PATH),
    original_crop
)

print()
print(
    "Original crop saved:"
)

print(
    CROP_PATH
)


# ============================================================
# CREATE PADDED CROP
# ============================================================

print()
print(
    "Creating padded plate crop..."
)

padded_crop = crop_with_padding(
    frame,
    x1,
    y1,
    x2,
    y2,
    padding_ratio=0.15
)


if padded_crop is None or padded_crop.size == 0:

    raise RuntimeError(
        "Could not create padded plate crop."
    )


cv2.imwrite(
    str(PADDED_CROP_PATH),
    padded_crop
)


print(
    "Padded crop saved:"
)

print(
    PADDED_CROP_PATH
)

print(
    "Padded crop resolution:",
    padded_crop.shape[1],
    "x",
    padded_crop.shape[0]
)


# ============================================================
# OCR VARIANTS
# ============================================================

print()
print(
    "Creating OCR variants..."
)

variants = create_variants(
    padded_crop
)

print(
    "Total variants:",
    len(variants)
)


# ============================================================
# OCR
# ============================================================

all_results = []


for variant_name, image in variants:

    print()
    print("--------------------------------")
    print(
        "OCR variant:",
        variant_name
    )
    print("--------------------------------")

    try:

        result, _ = ocr(
            image
        )

    except Exception as error:

        print(
            "OCR error:",
            error
        )

        continue


    if not result:

        print(
            "No text detected."
        )

        continue


    found = False


    for item in result:

        if len(item) < 3:
            continue

        raw_text = str(
            item[1]
        )

        confidence = float(
            item[2]
        )

        normalized = normalize_text(
            raw_text
        )

        if not normalized:
            continue

        found = True

        valid_format = (
            looks_like_indian_plate(
                normalized
            )
        )

        print(
            "Raw text:",
            raw_text
        )

        print(
            "Normalized:",
            normalized
        )

        print(
            "OCR confidence:",
            round(
                confidence,
                4
            )
        )

        print(
            "Indian plate format:",
            valid_format
        )

        all_results.append(
            {
                "variant": variant_name,
                "text": normalized,
                "confidence": confidence,
                "valid_format": valid_format
            }
        )


    if not found:

        print(
            "No usable text detected."
        )


# ============================================================
# RESULTS
# ============================================================

print()
print("================================")
print("ALL OCR RESULTS")
print("================================")


if not all_results:

    print(
        "No usable OCR results."
    )

else:

    for result in all_results:

        print(
            f"{result['variant']}: "
            f"{result['text']} "
            f"confidence="
            f"{result['confidence']:.4f} "
            f"valid="
            f"{result['valid_format']}"
        )


# ============================================================
# BEST RAW OCR RESULT
# ============================================================

print()
print("================================")
print("BEST RAW OCR RESULT")
print("================================")


if all_results:

    best_raw = max(
        all_results,
        key=lambda item: item["confidence"]
    )

    print(
        "Variant:",
        best_raw["variant"]
    )

    print(
        "Text:",
        best_raw["text"]
    )

    print(
        "Confidence:",
        round(
            best_raw["confidence"],
            4
        )
    )

    print(
        "Valid Indian format:",
        best_raw["valid_format"]
    )

else:

    print(
        "No OCR result."
    )


# ============================================================
# FINISH
# ============================================================

print()
print("================================")
print("TEST COMPLETE")
print("================================")