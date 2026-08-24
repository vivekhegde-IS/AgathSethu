"""
Vehicle representation and state tracking for Member 1 simulation.
Maps CARLA actor IDs to stable project vehicle IDs (V001, V002).
"""

from typing import Dict, Any, Tuple


class Vehicle:
    """Represents a vehicle state during simulation."""
    
    def __init__(
        self,
        vehicle_id: str,
        plate_number: str,
        carla_actor_id: int = -1,
        role: str = "PARTICIPANT",
        initial_speed_kmh: float = 40.0
    ):
        self.vehicle_id = vehicle_id
        self.plate_number = plate_number
        self.carla_actor_id = carla_actor_id
        self.role = role
        self.speed_mps = initial_speed_kmh / 3.6
        
        # State vectors
        self.position = (0.0, 0.0, 0.0)  # x, y, z in meters
        self.velocity = (self.speed_mps, 0.0, 0.0)  # vx, vy, vz in m/s
        self.accel = (0.0, 0.0, 9.81)  # ax, ay, az in m/s^2 (includes gravity)
        self.gyro = (0.0, 0.0, 0.0)  # gx, gy, gz in rad/s
        
    def update_state(
        self,
        position: Tuple[float, float, float],
        velocity: Tuple[float, float, float],
        accel: Tuple[float, float, float],
        gyro: Tuple[float, float, float]
    ):
        """Updates instantaneous state vectors."""
        self.position = position
        self.velocity = velocity
        self.accel = accel
        self.gyro = gyro

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "plate_number": self.plate_number,
            "carla_actor_id": self.carla_actor_id,
            "role": self.role,
            "position": {"x": self.position[0], "y": self.position[1], "z": self.position[2]},
            "speed_kmh": self.speed_mps * 3.6
        }
