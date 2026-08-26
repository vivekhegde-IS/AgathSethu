import cv2
import numpy as np
from typing import List, Tuple, Optional

class PlateDetector:
    """Extracts license plate Region of Interest (ROI) and pre-processes images for OCR."""

    def preprocess_plate_image(self, crop_image: np.ndarray) -> np.ndarray:
        """Applies grayscale, noise removal, and adaptive thresholding to enhance OCR readability."""
        if crop_image is None or crop_image.size == 0:
            return crop_image

        # Convert to grayscale if BGR
        if len(crop_image.shape) == 3:
            gray = cv2.cvtColor(crop_image, cv2.COLOR_BGR2GRAY)
        else:
            gray = crop_image

        # Resize for clearer character recognition
        h, w = gray.shape[:2]
        if w < 120 or h < 40:
            scale = max(2.0, 150.0 / max(w, 1))
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

        # Contrast adjustment (CLAHE)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # Bilateral filter to smooth noise while keeping edges sharp
        filtered = cv2.bilateralFilter(enhanced, 11, 17, 17)

        return filtered

    def locate_plate_roi(self, vehicle_crop: np.ndarray) -> Optional[np.ndarray]:
        """Locates candidate license plate ROI within a vehicle crop image using edge/contour analysis."""
        if vehicle_crop is None or vehicle_crop.size == 0:
            return None

        prep = self.preprocess_plate_image(vehicle_crop)
        edged = cv2.Canny(prep, 30, 200)

        contours, _ = cv2.findContours(edged, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]

        for cnt in contours:
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            if len(approx) == 4:
                x, y, w, h = cv2.boundingRect(approx)
                aspect_ratio = float(w) / max(1, float(h))
                if 2.0 <= aspect_ratio <= 6.0:  # Typical rectangular license plate ratio
                    return vehicle_crop[y:y+h, x:x+w]

        # Default fallback to lower rectangle of vehicle (where plates usually reside)
        vh, vw = vehicle_crop.shape[:2]
        plate_region = vehicle_crop[int(vh * 0.6):vh, int(vw * 0.2):int(vw * 0.8)]
        return plate_region
