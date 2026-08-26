from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional
from member2.anpr.ocr import OCRResult

@dataclass
class AggregatedPlateResult:
    track_id: str
    camera_id: str
    junction_id: str
    best_plate_number: str
    confidence: float
    total_observations: int

class MultiFramePlateAggregator:
    """Aggregates OCR results over multiple camera frames using majority voting and confidence weighting."""

    def __init__(self, min_observations: int = 1):
        self.min_observations = min_observations
        # Key: (camera_id, track_id) -> list of OCRResult
        self.observations: Dict[tuple, List[OCRResult]] = defaultdict(list)
        self.junction_map: Dict[tuple, str] = {}

    def add_observation(self, camera_id: str, junction_id: str, track_id: str, ocr_result: OCRResult):
        if ocr_result and ocr_result.cleaned_plate:
            key = (camera_id, track_id)
            self.observations[key].append(ocr_result)
            self.junction_map[key] = junction_id

    def get_aggregated_plate(self, camera_id: str, track_id: str) -> Optional[AggregatedPlateResult]:
        key = (camera_id, track_id)
        results = self.observations.get(key, [])
        if not results or len(results) < self.min_observations:
            return None

        # Score candidates by sum of confidence scores
        plate_scores: Dict[str, float] = defaultdict(float)
        plate_counts: Dict[str, int] = defaultdict(int)

        for res in results:
            plate_scores[res.cleaned_plate] += res.confidence
            plate_counts[res.cleaned_plate] += 1

        best_plate = max(plate_scores.keys(), key=lambda p: plate_scores[p])
        avg_conf = plate_scores[best_plate] / plate_counts[best_plate]

        return AggregatedPlateResult(
            track_id=track_id,
            camera_id=camera_id,
            junction_id=self.junction_map.get(key, "J02"),
            best_plate_number=best_plate,
            confidence=round(avg_conf, 3),
            total_observations=len(results)
        )
