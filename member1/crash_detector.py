"""
Member 1: Crash Detector Engine Entrypoint Wrapper.
Re-exports CrashDetector from member1.imu.crash_detector.
"""

from member1.imu.crash_detector import CrashDetector

__all__ = ["CrashDetector"]
