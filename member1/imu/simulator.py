"""
Reusable 6-axis IMU Sensor Simulator module.
Generates timestamped accelerometer (ax, ay, az) and gyroscope (gx, gy, gz) readings with realistic noise.
"""

import random
from typing import Dict, Any, Tuple, List


class IMUSimulator:
    """Simulates a 6-axis Inertial Measurement Unit (IMU)."""

    def __init__(
        self,
        sampling_rate_hz: float = 50.0,
        accel_noise_std: float = 0.05,
        gyro_noise_std: float = 0.02,
        gravity_m_s2: float = 9.81
    ):
        self.sampling_rate = sampling_rate_hz
        self.accel_noise_std = accel_noise_std
        self.gyro_noise_std = gyro_noise_std
        self.gravity = gravity_m_s2

    def add_noise_to_accel(self, accel: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Adds Gaussian noise to accelerometer tuple."""
        ax = accel[0] + random.gauss(0, self.accel_noise_std)
        ay = accel[1] + random.gauss(0, self.accel_noise_std)
        az = accel[2] + random.gauss(0, self.accel_noise_std)
        return (round(ax, 4), round(ay, 4), round(az, 4))

    def add_noise_to_gyro(self, gyro: Tuple[float, float, float]) -> Tuple[float, float, float]:
        """Adds Gaussian noise to gyroscope tuple."""
        gx = gyro[0] + random.gauss(0, self.gyro_noise_std)
        gy = gyro[1] + random.gauss(0, self.gyro_noise_std)
        gz = gyro[2] + random.gauss(0, self.gyro_noise_std)
        return (round(gx, 4), round(gy, 4), round(gz, 4))

    def generate_sample(
        self,
        timestamp_sim: float,
        vehicle_id: str,
        clean_accel: Tuple[float, float, float],
        clean_gyro: Tuple[float, float, float]
    ) -> Dict[str, Any]:
        """Generates a single noisy IMU sample dictionary."""
        noisy_accel = self.add_noise_to_accel(clean_accel)
        noisy_gyro = self.add_noise_to_gyro(clean_gyro)

        return {
            "timestamp_sim": timestamp_sim,
            "vehicle_id": vehicle_id,
            "accelerometer": {
                "ax": noisy_accel[0],
                "ay": noisy_accel[1],
                "az": noisy_accel[2]
            },
            "gyroscope": {
                "gx": noisy_gyro[0],
                "gy": noisy_gyro[1],
                "gz": noisy_gyro[2]
            }
        }
