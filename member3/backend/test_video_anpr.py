from pathlib import Path
import json
import sys

from app.services.routine_violation_video.processor import (
    process_video,
)


# ============================================================
# TEST VIDEO
# ============================================================

BACKEND_DIR = Path(__file__).resolve().parent

# Change ONLY this filename if your test video has a
# different name.
#
# Do NOT hardcode a plate number.
TEST_VIDEO = (
    BACKEND_DIR
    / "test_video.mp4"
)


OUTPUT_DIR = (
    BACKEND_DIR
    / "test_video_output"
)


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("VIDEO ANPR TEST")
    print("=" * 70)

    print(
        f"Backend: {BACKEND_DIR}"
    )

    print(
        f"Video: {TEST_VIDEO}"
    )

    print(
        f"Output: {OUTPUT_DIR}"
    )

    # --------------------------------------------------------
    # CHECK VIDEO
    # --------------------------------------------------------

    if not TEST_VIDEO.exists():

        print()
        print("ERROR")
        print("=" * 70)
        print(
            "Test video was not found."
        )
        print()
        print(
            f"Expected:"
        )
        print(
            TEST_VIDEO
        )
        print()
        print(
            "Put your test video in the backend "
            "folder or change TEST_VIDEO in "
            "test_video_anpr.py."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # RUN PROCESSOR
    # --------------------------------------------------------

    try:

        result = process_video(
            video_path=TEST_VIDEO,
            output_dir=OUTPUT_DIR,
        )

    except Exception as exc:

        print()
        print("=" * 70)
        print("PROCESSING ERROR")
        print("=" * 70)

        print(
            f"{type(exc).__name__}: {exc}"
        )

        raise

    # --------------------------------------------------------
    # PRINT COMPLETE RESULT
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("TEST RESULT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    print()
    print("=" * 70)
    print("TEST FINISHED")
    print("=" * 70)


if __name__ == "__main__":
    main()