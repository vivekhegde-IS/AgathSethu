"""
CLI runner for Member 1 demonstration scenario.
Executes vehicle dynamics simulation, IMU sensor simulation, crash detection,
evaluation benchmark, and visualization plotting.
"""

import sys
import os
import logging

# Ensure project root is in python path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from member1.run_member1 import run_member1_pipeline

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


def main():
    print("=" * 60)
    print("MEMBER 1: CARLA / KINEMATIC CRASH DETECTION DEMONSTRATION")
    print("=" * 60)
    
    success = run_member1_pipeline()
    if success:
        print("\n[SUCCESS] Member 1 demonstration completed successfully.")
        sys.exit(0)
    else:
        print("\n[ERROR] Member 1 demonstration encountered errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
