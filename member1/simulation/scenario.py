"""
Scenario Manager for Member 1 Demo:
Simulates reproducible vehicle trajectories and collision physics at Junction J02.
Supports CARLA live engine or Kinematic Physics fallback mode.
"""

import math
import random
import logging
from typing import Dict, List, Any, Tuple, Optional
from member1.simulation.vehicles import Vehicle

logger = logging.getLogger("Member1.Scenario")


class ScenarioManager:
    """Manages scenario execution and vehicle telemetry generation."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        sim_cfg = config.get("simulation", {})
        self.sampling_rate = sim_cfg.get("sampling_rate_hz", 50.0)
        self.dt = 1.0 / self.sampling_rate
        self.duration = sim_cfg.get("duration_seconds", 10.0)
        self.crash_time = sim_cfg.get("crash_timestamp_sim", 102.43)
        self.start_time = self.crash_time - 2.43  # e.g., t=100.0s start
        self.junction_id = sim_cfg.get("junction_id", "J02")
        self.location = sim_cfg.get("location", {"x": 104.2, "y": 52.7, "z": 0.3})

        # Initialize vehicles from config
        self.vehicles: Dict[str, Vehicle] = {}
        veh_cfg = config.get("vehicles", {})
        for v_id, cfg in veh_cfg.items():
            self.vehicles[v_id] = Vehicle(
                vehicle_id=v_id,
                plate_number=cfg.get("plate_number", "UNKNOWN"),
                carla_actor_id=cfg.get("carla_id", -1),
                role=cfg.get("role", "PARTICIPANT"),
                initial_speed_kmh=cfg.get("initial_speed_kmh", 40.0)
            )

    def generate_kinematic_telemetry(self) -> Tuple[List[float], Dict[str, List[Dict[str, Any]]]]:
        """
        Generates deterministic kinematic telemetry for all vehicles over time.
        Includes pre-crash normal motion, high-G collision deceleration pulse, and post-crash dynamics.
        
        Returns:
            timestamps: List of simulation timestamps (seconds)
            telemetry: Dict mapping vehicle_id -> list of telemetry frames
        """
        num_steps = int(self.duration * self.sampling_rate)
        timestamps = [self.start_time + i * self.dt for i in range(num_steps)]
        
        telemetry_data: Dict[str, List[Dict[str, Any]]] = {v_id: [] for v_id in self.vehicles}
        
        # Vehicle params
        v1_decel_g = self.config.get("vehicles", {}).get("V001", {}).get("impact_decel_g", 5.8)
        v2_decel_g = self.config.get("vehicles", {}).get("V002", {}).get("impact_decel_g", 6.2)
        v1_gyro_pulse = self.config.get("vehicles", {}).get("V001", {}).get("gyro_pulse_rads", 3.7)
        v2_gyro_pulse = self.config.get("vehicles", {}).get("V002", {}).get("gyro_pulse_rads", 4.1)

        gravity = self.config.get("imu", {}).get("gravity_m_s2", 9.81)

        for step_idx, t in enumerate(timestamps):
            rel_t = t - self.crash_time
            
            # --- VEHICLE 1 (V001 - KA01AB1234 - Victim) ---
            # Travel along X axis towards J02
            if rel_t < 0:
                # Normal driving before crash
                ax = 0.1 * math.sin(t * 2)  # slight speed variation
                ay = 0.05 * math.cos(t * 1.5)
                az = gravity + 0.02 * math.sin(t * 3)
                gx = 0.01 * math.sin(t)
                gy = 0.01 * math.cos(t)
                gz = 0.02 * math.sin(t * 0.5)
                x = self.location["x"] + rel_t * 11.1  # 40 km/h approx 11.1 m/s
                y = self.location["y"]
                z = self.location["z"]
            elif 0 <= rel_t <= 0.20:
                # Impact phase (Crash pulse ~200ms)
                pulse_ratio = math.sin((rel_t / 0.20) * math.pi)
                ax = -v1_decel_g * gravity * pulse_ratio
                ay = (v1_decel_g * 0.4) * gravity * pulse_ratio
                az = gravity + (v1_decel_g * 0.3) * gravity * pulse_ratio
                gx = v1_gyro_pulse * pulse_ratio
                gy = -v1_gyro_pulse * 0.7 * pulse_ratio
                gz = v1_gyro_pulse * 1.2 * pulse_ratio
                x = self.location["x"]
                y = self.location["y"]
                z = self.location["z"]
            else:
                # Post-crash rest / minor decay
                decay = math.exp(-(rel_t - 0.20) * 5.0)
                ax = -0.5 * decay
                ay = 0.2 * decay
                az = gravity + 0.05 * decay
                gx = 0.1 * decay
                gy = 0.05 * decay
                gz = 0.15 * decay
                x = self.location["x"] + 0.5
                y = self.location["y"] + 0.2
                z = self.location["z"]

            telemetry_data["V001"].append({
                "timestamp_sim": round(t, 4),
                "position": {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
                "accel": (round(ax, 4), round(ay, 4), round(az, 4)),
                "gyro": (round(gx, 4), round(gy, 4), round(gz, 4))
            })

            # --- VEHICLE 2 (V002 - KA05XY5678 - Suspect) ---
            # Travel along Y axis into intersection J02, hits V001 then flees
            if rel_t < 0:
                # Normal driving
                ax = 0.05 * math.cos(t * 1.8)
                ay = 0.12 * math.sin(t * 2.2)
                az = gravity + 0.03 * math.cos(t * 2.5)
                gx = 0.015 * math.cos(t)
                gy = 0.01 * math.sin(t)
                gz = 0.01 * math.cos(t * 0.8)
                x = self.location["x"]
                y = self.location["y"] + rel_t * 12.5  # 45 km/h approx 12.5 m/s
                z = self.location["z"]
            elif 0 <= rel_t <= 0.20:
                # Impact phase
                pulse_ratio = math.sin((rel_t / 0.20) * math.pi)
                ax = (v2_decel_g * 0.5) * gravity * pulse_ratio
                ay = -v2_decel_g * gravity * pulse_ratio
                az = gravity + (v2_decel_g * 0.4) * gravity * pulse_ratio
                gx = -v2_gyro_pulse * pulse_ratio
                gy = v2_gyro_pulse * 0.8 * pulse_ratio
                gz = -v2_gyro_pulse * 1.5 * pulse_ratio
                x = self.location["x"]
                y = self.location["y"]
                z = self.location["z"]
            else:
                # Hit-and-run fleeing phase: accelerates away towards J03
                flee_t = rel_t - 0.20
                ax = 1.5  # accelerating away
                ay = 0.5
                az = gravity + 0.02 * math.sin(t)
                gx = 0.05 * math.sin(t)
                gy = 0.03 * math.cos(t)
                gz = 0.02
                x = self.location["x"] + flee_t * 10.0
                y = self.location["y"] + flee_t * 15.0
                z = self.location["z"]

            telemetry_data["V002"].append({
                "timestamp_sim": round(t, 4),
                "position": {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2)},
                "accel": (round(ax, 4), round(ay, 4), round(az, 4)),
                "gyro": (round(gx, 4), round(gy, 4), round(gz, 4))
            })

        return timestamps, telemetry_data
