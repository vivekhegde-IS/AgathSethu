"""
Plate OCR with per-character confidences.

Engine: RapidOCR's PP-OCRv3 text recognizer (the PaddleOCR recognition model,
run through onnxruntime - already installed). Instead of RapidOCR's generic
"detect text boxes, then recognise" call, plate crops go straight to the
recognizer, and the CTC output is decoded here with an allowlist
(A-Z, 0-9) so that:
  * every character gets its own confidence (needed for character voting),
  * Chinese / punctuation classes can never be emitted,
  * no text-detection pass is needed (the plate detector already found it).

Preprocessing per crop: fixed-height upscale + grayscale; CLAHE + mild
sharpening and the inverted image are retried when confidence is low. Two-line
plates (aspect < TWO_LINE_ASPECT) are split into top and bottom lines (at the
midpoint and at the detected row gap, with the IND emblem strip trimmed) and
each line is read separately (top then bottom); the single-line read is also
kept so the caller can pick whichever validates better.
"""

from __future__ import annotations

import string
import threading
from dataclasses import dataclass

import cv2
import numpy as np

ALLOWLIST = string.ascii_uppercase + string.digits
# Crop preprocessing.
OCR_HEIGHT = 112              # fixed height after upscaling (px)
TWO_LINE_ASPECT = 2.5         # width/height below this = two-line plate
INVERT_BELOW_CONF = 0.60      # also try the inverted image under this conf
# Quality gate: crops below these are not OCR'd at all.
MIN_PLATE_HEIGHT = 14
MIN_PLATE_WIDTH = 28
MIN_SHARPNESS = 25.0          # variance of Laplacian on the gray crop
OCR_THREADS = 2
WIDTH_BUCKET = 160            # recognizer input widths are multiples of this
MAX_REC_WIDTH = 960


@dataclass
class OcrRead:
    text: str
    confidences: list[float]
    variant: str              # "single" | "two-line" | "+inverted"

    @property
    def mean_conf(self) -> float:
        return sum(self.confidences) / len(self.confidences) if self.confidences else 0.0


_engine = None
_lock = threading.Lock()


class _Recognizer:
    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()
        # rapidocr-onnxruntime renamed the recognizer attribute: <=1.3.x used
        # ``text_recognizer`` while 1.4.x (the version we pin) exposes
        # ``text_rec``. Support both so the OCR loads on either release.
        rec = getattr(engine, "text_recognizer", None) or getattr(engine, "text_rec")
        model_path = rec.session.session._model_path
        # Recognition-only: the PP-OCR recognizer is run directly on the tight
        # plate crop (no text-detection stage). OpenVINO CPU with a small
        # thread pool measured fastest (45 ms vs 76 ms onnxruntime/4 threads
        # per 2-line batch); onnxruntime is the fallback.
        try:
            import openvino as ov

            core = ov.Core()
            compiled = core.compile_model(core.read_model(model_path), "CPU",
                                          {"INFERENCE_NUM_THREADS": OCR_THREADS})
            local = threading.local()

            def run(batch):
                # one infer request per thread, so vehicles can be OCR'd in parallel
                if not hasattr(local, "request"):
                    local.request = compiled.create_infer_request()
                local.request.infer([batch])
                return [local.request.get_output_tensor(0).data.copy()]

            self.session = run
            self.thread_safe = True
            self.backend = f"OpenVINO CPU ({OCR_THREADS} threads), recognition-only"
        except Exception:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = OCR_THREADS
            options.inter_op_num_threads = 1
            ort_session = ort.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])
            input_name = ort_session.get_inputs()[0].name
            self.session = lambda batch: ort_session.run(None, {input_name: batch})
            self.thread_safe = False
            self.backend = f"onnxruntime CPU ({OCR_THREADS} threads), recognition-only"
        self.shape = rec.rec_image_shape            # [3, 48, 320]
        characters = rec.postprocess_op.character   # index 0 = CTC blank
        self.allowed = np.array(
            [0] + [i for i, ch in enumerate(characters) if ch in ALLOWLIST], dtype=np.int64)
        self.labels = [characters[i] for i in self.allowed]
        self.lock = threading.Lock()

    def _prepare(self, image, width):
        _, height, _ = self.shape
        h, w = image.shape[:2]
        resized_w = min(width, max(8, int(np.ceil(height * w / max(1, h)))))
        resized = cv2.resize(image, (resized_w, height)).astype(np.float32)
        resized = (resized.transpose(2, 0, 1) / 255.0 - 0.5) / 0.5
        padded = np.zeros((3, height, width), dtype=np.float32)
        padded[:, :, :resized_w] = resized
        return padded

    def __call__(self, images: list[np.ndarray]) -> list[tuple[str, list[float]]]:
        if not images:
            return []
        _, height, base_width = self.shape
        ratio = max(img.shape[1] / max(1, img.shape[0]) for img in images)
        # round the batch width up to a fixed bucket: OpenVINO then sees a
        # handful of input shapes instead of a new one per crop
        width = max(base_width, int(np.ceil(height * ratio)))
        width = min(MAX_REC_WIDTH, int(np.ceil(width / WIDTH_BUCKET) * WIDTH_BUCKET))
        batch = np.stack([self._prepare(img, width) for img in images])
        if self.thread_safe:
            preds = self.session(batch)[0]          # (N, T, classes)
        else:
            with self.lock:
                preds = self.session(batch)[0]
        results = []
        for pred in preds:
            probs = pred[:, self.allowed]           # allowlist + blank only
            best = probs.argmax(axis=1)
            best_p = probs.max(axis=1)
            text, confs, previous = [], [], 0
            for index, p in zip(best, best_p):
                if index != 0 and index != previous:
                    text.append(self.labels[index])
                    confs.append(float(p))
                elif index != 0 and index == previous and confs:
                    confs[-1] = max(confs[-1], float(p))
                previous = index
            results.append(("".join(text), confs))
        return results


def get_recognizer() -> _Recognizer:
    global _engine
    with _lock:
        if _engine is None:
            _engine = _Recognizer()
        return _engine


def sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var()) if gray.size else 0.0


def passes_quality(crop: np.ndarray) -> tuple[bool, float, str]:
    """(ok, sharpness, reason). Too-small or too-blurry crops are skipped."""
    h, w = crop.shape[:2]
    if h < MIN_PLATE_HEIGHT or w < MIN_PLATE_WIDTH:
        return False, 0.0, f"too small ({w}x{h})"
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sharp = sharpness(gray)
    if sharp < MIN_SHARPNESS:
        return False, sharp, f"too blurry (laplacian var {sharp:.0f})"
    return True, sharp, ""


def preprocess(crop: np.ndarray, height: int = OCR_HEIGHT) -> np.ndarray:
    """Upscale to a fixed height, grayscale, CLAHE, mild unsharp mask."""
    h, w = crop.shape[:2]
    scale = height / max(1, h)
    image = cv2.resize(crop, (max(1, int(w * scale)), height),
                       interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 8)).apply(gray)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
    return cv2.addWeighted(gray, 1.5, blur, -0.5, 0)


def split_rows(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split a two-line plate at the row gap: the darkest-ink-free row band in
    the middle 35-65% of the height (falls back to the exact middle)."""
    h = gray.shape[0]
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                   cv2.THRESH_BINARY_INV, 15, 10)
    ink = binary.sum(axis=1).astype(np.float64)
    lo, hi = int(h * 0.35), max(int(h * 0.35) + 1, int(h * 0.65))
    cut = lo + int(np.argmin(ink[lo:hi])) if hi > lo else h // 2
    pad = max(1, h // 20)
    return gray[: min(h, cut + pad)], gray[max(0, cut - pad):]


def _to_bgr(gray):
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


# Left strip dropped from each row of a two-line plate: the vertical "IND"
# emblem of HSRP plates sits there and is otherwise read as extra characters.
EMBLEM_TRIM = 0.06


def _light(crop: np.ndarray) -> np.ndarray:
    """Default input: fixed-height upscale + grayscale only. Measured on the
    sample video, the recognizer reads plain grayscale better than
    CLAHE/sharpened input, so those are used only as a low-confidence retry."""
    h, w = crop.shape[:2]
    scale = OCR_HEIGHT / max(1, h)
    image = cv2.resize(crop, (max(1, int(w * scale)), OCR_HEIGHT),
                       interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _line_variants(gray: np.ndarray, two_line: bool, tag: str):
    """(name, [line images]) variants; two-line plates are read top then
    bottom, split both at the midpoint and at the detected row gap."""
    if not two_line:
        return [(f"single{tag}", [gray])]
    h, w = gray.shape[:2]
    trim = int(w * EMBLEM_TRIM)
    pad = max(1, h // 25)
    mid_top, mid_bottom = gray[: h // 2 + pad], gray[h // 2 - pad:]
    gap_top, gap_bottom = split_rows(gray)
    return [
        (f"two-line{tag}", [mid_top[:, trim:], mid_bottom[:, trim:]]),
        (f"two-line-gap{tag}", [gap_top[:, trim:], gap_bottom[:, trim:]]),
        (f"two-line-untrimmed{tag}", [mid_top, mid_bottom]),
        (f"single{tag}", [gray]),
    ]


def read_plate(crop: np.ndarray, good_enough=None,
               two_line_aspect: float | None = None) -> list[OcrRead]:
    """OCR a plate crop. Returns every usable reading; the caller validates
    them and keeps the best.

    ``two_line_aspect`` overrides TWO_LINE_ASPECT for one call (0 = always
    read as a single line, for feeds whose plates are known single-line).

    Staged to keep OCR cheap: the primary variant (two-line: midpoint split
    with the emblem strip trimmed; single-line: the whole crop) runs first.
    If ``good_enough(read)`` accepts it, nothing else runs; otherwise the other
    split variants run as one batch, then CLAHE/sharpened and inverted
    retries when confidence is still low."""
    recognizer = get_recognizer()
    h, w = crop.shape[:2]
    threshold = TWO_LINE_ASPECT if two_line_aspect is None else two_line_aspect
    two_line = (w / max(1, h)) < threshold

    def run(variants):
        images = [_to_bgr(line) for _, lines in variants for line in lines]
        outputs = iter(recognizer(images))
        reads = []
        for name, lines in variants:
            parts = [next(outputs) for _ in lines]
            if all(text for text, _ in parts):
                reads.append(OcrRead("".join(t for t, _ in parts),
                                     [c for _, confs in parts for c in confs], name))
        return reads

    def accepted(reads):
        return good_enough is not None and any(good_enough(r) for r in reads)

    variants = _line_variants(_light(crop), two_line, "")
    # stage 1: the primary read (1-2 line images)
    reads = run(variants[:1])
    if accepted(reads):
        return reads
    # stage 2: the other splits of the same image
    reads += run(variants[1:])
    if accepted(reads) or (reads and max(r.mean_conf for r in reads) >= INVERT_BELOW_CONF):
        return reads
    # stage 3 (low confidence only): CLAHE + sharpened, and inverted
    enhanced = preprocess(crop)
    reads += run(_line_variants(enhanced, two_line, "+clahe")[:1]
                 + _line_variants(255 - enhanced, two_line, "+inverted")[:1])
    return reads
