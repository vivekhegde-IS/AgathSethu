"""
Hybrid Transparent Crash Detector Engine.
Uses explainable score-based thresholding combining G-force, jerk, and angular velocity.
Generates CRASH_DETECTED events conforming strictly to shared contract schemas.
Ground truth collision information is NEVER accessed during inference.
"""

import logging
import uuid
from typing import Dict, Any, Optional, List, Tuple
from member1.imu.features import FeatureExtractor

logger = logging.getLogger("Member1.CrashDetector")


class CrashDetector:
    """Transparent hybrid threshold crash detector."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        cd_cfg = config.get("crash_detection", {})
        
        # Thresholds
        self.g_thresh = cd_cfg.get("acceleration_threshold_g", 4.5)
        self.jerk_thresh = cd_cfg.get("jerk_threshold", 25.0)
        self.gyro_thresh = cd_cfg.get("gyro_threshold", 2.5)
        self.conf_thresh = cd_cfg.get("confidence_threshold", 0.70)
        
        # Weights
        weights = cd_cfg.get("weights", {"acceleration": 0.50, "jerk": 0.30, "gyro": 0.20})
        self.w_accel = weights.get("acceleration", 0.50)
        self.w_jerk = weights.get("jerk", 0.30)
        self.w_gyro = weights.get("gyro", 0.20)

        self.junction_id = config.get("simulation", {}).get("junction_id", "J02")
        self.location = config.get("simulation", {}).get("location", {"x": 104.2, "y": 52.7, "z": 0.3})

        # Feature extractor
        sampling_rate = config.get("imu", {}).get("sampling_rate_hz", 50.0)
        self.feature_extractor = FeatureExtractor(
            gravity=config.get("imu", {}).get("gravity_m_s2", 9.81),
            window_seconds=cd_cfg.get("window_seconds", 0.5),
            sampling_rate_hz=sampling_rate
        )

        # Detection state & refractory cooldown per vehicle
        self.last_crash_time: Dict[str, float] = {}
        self.cooldown_seconds = 2.0
        self.event_counter = 1

    def calculate_confidence(self, g_force: float, jerk: float, gyro_mag: float) -> Tuple[float, Dict[str, float]]:
        """
        Calculates explainable confidence score from normalized sub-scores.
        
        Returns:
            confidence (0.0 to 1.0)
            scores dict (individual feature sub-scores)
        """
        # Accel score (1.0g is normal driving, g_thresh is threshold)
        if g_force <= 1.5:
            accel_score = 0.0
        else:
            accel_score = min(1.0, (g_force - 1.5) / max(0.1, self.g_thresh - 1.5))

        # Jerk score (0 to jerk_thresh)
        if jerk <= 5.0:
            jerk_score = 0.0
        else:
            jerk_score = min(1.0, (jerk - 5.0) / max(0.1, self.jerk_thresh - 5.0))

        # Gyro score (0 to gyro_thresh)
        if gyro_mag <= 0.5:
            gyro_score = 0.0
        else:
            gyro_score = min(1.0, (gyro_mag - 0.5) / max(0.1, self.gyro_thresh - 0.5))

        confidence = (
            self.w_accel * accel_score +
            self.w_jerk * jerk_score +
            self.w_gyro * gyro_score
        )

        scores = {
            "accel_score": round(accel_score, 3),
            "jerk_score": round(jerk_score, 3),
            "gyro_score": round(gyro_score, 3)
        }

        return round(confidence, 3), scores

    def process_imu_sample(
        self,
        imu_sample: Dict[str, Any],
        vehicle_location: Optional[Dict[str, float]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Processes a single IMU sample through feature calculation and crash scoring.
        
        Returns:
            CRASH_DETECTED event dict if crash threshold met, else None.
        """
        features = self.feature_extractor.extract_features(imu_sample)
        v_id = features["vehicle_id"]
        t_sim = features["timestamp_sim"]
        g_force = features["g_force"]
        jerk = features["jerk"]
        gyro_mag = features["gyro_mag"]

        confidence, sub_scores = self.calculate_confidence(g_force, jerk, gyro_mag)

        # Check refractory cooldown
        if v_id in self.last_crash_time:
            if (t_sim - self.last_crash_time[v_id]) < self.cooldown_seconds:
                return None

        # Check detection condition
        if confidence >= self.conf_thresh:
            self.last_crash_time[v_id] = t_sim
            event_id = f"evt_crash_{self.event_counter:03d}"
            self.event_counter += 1

            loc = vehicle_location if vehicle_location else self.location

            event_payload = {
                "event_id": event_id,
                "event_type": "CRASH_DETECTED",
                "timestamp_sim": round(t_sim, 4),
                "source": "member1",
                "junction_id": self.junction_id,
                "vehicle_id": v_id,
                "confidence": confidence,
                "location": loc,
                "telemetry_summary": {
                    "max_g_force": g_force,
                    "jerk": jerk,
                    "gyro_magnitude": gyro_mag,
                    "scores": sub_scores
                }
            }

            logger.info(
                f"CRASH_DETECTED! Vehicle={v_id}, t={t_sim:.2f}s, g_force={g_force:.2f}g, "
                f"jerk={jerk:.1f}, gyro={gyro_mag:.2f}, conf={confidence:.2f}"
            )

            return event_payload

        return None
