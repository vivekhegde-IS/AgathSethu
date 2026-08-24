"""
Feature Calculation for Crash Detection.
Computes acceleration magnitude, G-force, jerk (da/dt), and angular velocity magnitude.
Maintains rolling sensor window for explainable evidence extraction.
"""

import math
from collections import deque
from typing import Dict, Any, List, Optional


class FeatureExtractor:
    """Extracts instantaneous and windowed kinematic features from IMU streams."""

    def __init__(self, gravity: float = 9.81, window_seconds: float = 0.5, sampling_rate_hz: float = 50.0):
        self.gravity = gravity
        self.dt = 1.0 / sampling_rate_hz
        self.window_size = max(5, int(window_seconds * sampling_rate_hz))
        
        # State tracking per vehicle
        self.prev_a_mag: Dict[str, float] = {}
        self.prev_time: Dict[str, float] = {}
        self.window_buffers: Dict[str, deque] = {}

    def extract_features(self, imu_sample: Dict[str, Any]) -> Dict[str, Any]:
        """
        Processes a raw IMU sample and returns calculated features.
        
        Returns dict containing:
            a_mag: Acceleration magnitude (m/s^2)
            g_force: G-force magnitude (g)
            jerk: Jerk (g/s)
            gyro_mag: Gyroscope angular velocity magnitude (rad/s)
        """
        v_id = imu_sample["vehicle_id"]
        t = imu_sample["timestamp_sim"]
        acc = imu_sample["accelerometer"]
        gyro = imu_sample["gyroscope"]

        # 1. Acceleration magnitude
        ax, ay, az = acc["ax"], acc["ay"], acc["az"]
        a_mag = math.sqrt(ax * ax + ay * ay + az * az)

        # 2. G-force magnitude
        g_force = a_mag / self.gravity

        # 3. Angular velocity magnitude
        gx, gy, gz = gyro["gx"], gyro["gy"], gyro["gz"]
        gyro_mag = math.sqrt(gx * gx + gy * gy + gz * gz)

        # 4. Jerk calculation (delta g_force / delta t)
        if v_id in self.prev_a_mag and v_id in self.prev_time:
            delta_t = t - self.prev_time[v_id]
            if delta_t <= 0:
                delta_t = self.dt
            delta_g = abs(g_force - (self.prev_a_mag[v_id] / self.gravity))
            jerk = delta_g / delta_t
        else:
            jerk = 0.0

        # Update previous state
        self.prev_a_mag[v_id] = a_mag
        self.prev_time[v_id] = t

        features = {
            "timestamp_sim": t,
            "vehicle_id": v_id,
            "a_mag": round(a_mag, 4),
            "g_force": round(g_force, 4),
            "jerk": round(jerk, 4),
            "gyro_mag": round(gyro_mag, 4),
            "raw_accel": acc,
            "raw_gyro": gyro
        }

        # Maintain rolling window buffer
        if v_id not in self.window_buffers:
            self.window_buffers[v_id] = deque(maxlen=self.window_size * 2)
        self.window_buffers[v_id].append(features)

        return features

    def get_rolling_window(self, vehicle_id: str) -> List[Dict[str, Any]]:
        """Returns buffered window of samples for explainability evidence."""
        if vehicle_id in self.window_buffers:
            return list(self.window_buffers[vehicle_id])
        return []
