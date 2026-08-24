"""
Master Demonstration Runner for Hit-and-Run Detection System.
Executes Member 1 crash detection simulation pipeline.
"""

import sys
import os

# Ensure project root in python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from member1.run_member1 import run_member1_pipeline


def main():
    print("Executing Master Demonstration Runner...")
    success = run_member1_pipeline()
    if success:
        print("[DEMO SUCCESS] Member 1 pipeline executed cleanly.")
        sys.exit(0)
    else:
        print("[DEMO FAILURE] Member 1 pipeline failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
