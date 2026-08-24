"""
Signal Preprocessing and Noise Filtering for IMU Telemetry.
Provides moving average and low-pass filtering utilities.
"""

from typing import List, Dict, Any


class SignalFilter:
    """Applies noise filtering to raw IMU sensor channels."""

    def __init__(self, alpha: float = 0.8):
        """
        Args:
            alpha: Smoothing factor between 0.0 and 1.0 (higher = less smoothing, faster response).
        """
        self.alpha = alpha
        self.prev_accel = None
        self.prev_gyro = None

    def filter_sample(
        self,
        accel: Dict[str, float],
        gyro: Dict[str, float]
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """Applies exponential moving average to single sample."""
        if self.prev_accel is None:
            self.prev_accel = accel
            self.prev_gyro = gyro
            return accel, gyro

        filtered_accel = {
            "ax": self.alpha * accel["ax"] + (1 - self.alpha) * self.prev_accel["ax"],
            "ay": self.alpha * accel["ay"] + (1 - self.alpha) * self.prev_accel["ay"],
            "az": self.alpha * accel["az"] + (1 - self.alpha) * self.prev_accel["az"]
        }
        filtered_gyro = {
            "gx": self.alpha * gyro["gx"] + (1 - self.alpha) * self.prev_gyro["gx"],
            "gy": self.alpha * gyro["gy"] + (1 - self.alpha) * self.prev_gyro["gy"],
            "gz": self.alpha * gyro["gz"] + (1 - self.alpha) * self.prev_gyro["gz"]
        }

        self.prev_accel = filtered_accel
        self.prev_gyro = filtered_gyro
        return filtered_accel, filtered_gyro
