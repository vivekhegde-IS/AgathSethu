"""
Telemetry Visualization Module for Member 1 Demo.
Plots time vs Acceleration G-force, Jerk, and Angular Velocity.
Annotates CRASH_DETECTED trigger points and pre/post-crash windows.
Saves figure to member1/outputs/crash_sensor_plot.png.
"""

import os
import json
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
from typing import Dict, List, Any


def plot_telemetry_and_events(
    timestamps: List[float],
    telemetry_data: Dict[str, List[Dict[str, Any]]],
    events: List[Dict[str, Any]],
    output_path: str = "member1/outputs/crash_sensor_plot.png"
):
    """
    Generates telemetry plots with crash event markers.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    fig.suptitle("Member 1: Vehicle IMU Sensor Telemetry & Crash Detection", fontsize=14, fontweight="bold")

    colors = {"V001": "#1f77b4", "V002": "#ff7f0e", "V003": "#2ca02c"}

    for v_id, frames in telemetry_data.items():
        ts = [f["timestamp_sim"] for f in frames]
        
        # Calculate magnitudes for plotting
        g_forces = []
        gyro_mags = []
        jerks = [0.0]

        for i, f in enumerate(frames):
            ax, ay, az = f["accel"]
            gx, gy, gz = f["gyro"]
            a_mag = (ax**2 + ay**2 + az**2)**0.5
            g_force = a_mag / 9.81
            g_forces.append(g_force)
            
            gyro_mag = (gx**2 + gy**2 + gz**2)**0.5
            gyro_mags.append(gyro_mag)

            if i > 0:
                dt = ts[i] - ts[i - 1]
                if dt <= 0:
                    dt = 0.02
                jerk = abs(g_forces[i] - g_forces[i - 1]) / dt
                jerks.append(jerk)

        c = colors.get(v_id, "#7f7f7f")
        ax1.plot(ts, g_forces, label=f"Vehicle {v_id}", color=c, linewidth=1.8)
        ax2.plot(ts, jerks, label=f"Vehicle {v_id}", color=c, linewidth=1.8)
        ax3.plot(ts, gyro_mags, label=f"Vehicle {v_id}", color=c, linewidth=1.8)

    # Threshold lines
    ax1.axhline(y=4.5, color="r", linestyle="--", alpha=0.6, label="Crash G-Force Threshold (4.5g)")
    ax2.axhline(y=25.0, color="r", linestyle="--", alpha=0.6, label="Jerk Threshold (25 g/s)")
    ax3.axhline(y=2.5, color="r", linestyle="--", alpha=0.6, label="Gyro Threshold (2.5 rad/s)")

    # Plot CRASH_DETECTED event markers
    for evt in events:
        t_evt = evt["timestamp_sim"]
        v_evt = evt["vehicle_id"]
        conf = evt.get("confidence", 0.0)
        
        for ax in (ax1, ax2, ax3):
            ax.axvline(x=t_evt, color="red", linestyle=":", linewidth=2)
        
        ax1.annotate(
            f"CRASH DETECTED\n{v_evt} (Conf: {conf:.2f})",
            xy=(t_evt, 5.0),
            xytext=(t_evt + 0.3, 5.5),
            arrowprops=dict(facecolor="red", shrink=0.05, width=1.5, headwidth=8),
            fontweight="bold",
            color="darkred",
            fontsize=9
        )

    ax1.set_ylabel("G-Force (g)")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left")

    ax2.set_ylabel("Jerk (g/s)")
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="upper left")

    ax3.set_ylabel("Gyro Magnitude (rad/s)")
    ax3.set_xlabel("Simulation Time (seconds)")
    ax3.grid(True, linestyle=":", alpha=0.6)
    ax3.legend(loc="upper left")

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()

    print(f"[PLOT] Telemetry visualization saved to: {output_path}")


if __name__ == "__main__":
    # Test script execution
    print("Testing plot generator...")
