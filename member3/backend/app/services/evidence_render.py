"""Shared plate-evidence renderer.

One drawing routine for every evidence image that shows a vehicle and its plate:
the routine-violation cards (helmet pipeline) and the RFID next-junction
sighting cards use the same look:

  * red box around the vehicle with a short label,
  * blue box around the plate,
  * the plate crop zoomed into an inset at the top-left,
  * a black banner under the inset: plate text (white, red when unreadable)
    and a second line (state name / RFID info),
  * a footer line at the bottom-left ("J02 | frame N | t=...s").

Callers only decide WHAT to show; layout and style live here.
"""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

RED, GREEN, BLUE, WHITE, BLACK, YELLOW = (0, 0, 255), (0, 200, 0), (255, 170, 0), (255, 255, 255), (0, 0, 0), (0, 220, 255)


def draw_text(image, text, origin, scale, color, thickness):
    """Outlined text (black halo) that stays readable on any background."""
    cv2.putText(image, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, BLACK, thickness + 2, cv2.LINE_AA)
    cv2.putText(image, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def scale_unit(image: np.ndarray) -> tuple[float, int]:
    """(unit, line thickness) for an image: 1.0 at 1280 px wide."""
    unit = max(0.6, image.shape[1] / 1280.0)
    return unit, max(2, int(round(2 * unit)))


def draw_plate_evidence(
    image: np.ndarray,
    *,
    vehicle_box: Sequence[float] | None,
    vehicle_label: str | None,
    plate_box: Sequence[float] | None,
    plate_crop: np.ndarray | None,
    plate_label: str | None,
    second_line: str,
    footer: str,
    extra_lines: Sequence[str] = (),
    vehicle_color: tuple = RED,
) -> np.ndarray:
    """Draw the evidence overlay IN PLACE on ``image`` and return it.

    ``plate_label`` None renders "PLATE UNREADABLE" in red. ``plate_crop`` is
    only drawn as an inset when given. ``extra_lines`` are extra banner rows
    (e.g. "RFID MH12BR7814 | CONFIRMED").
    """
    height, width = image.shape[:2]
    unit, thick = scale_unit(image)

    if vehicle_box is not None:
        x1, y1, x2, y2 = [int(v) for v in vehicle_box]
        cv2.rectangle(image, (x1, y1), (x2, y2), vehicle_color, thick + 1)
        if vehicle_label:
            draw_text(image, vehicle_label, (x1, max(int(22 * unit), y1 - int(8 * unit))),
                      0.7 * unit, vehicle_color, thick)

    pad = int(12 * unit)
    banner_w = int(width * 0.32)
    top = pad
    if plate_box is not None:
        bx1, by1, bx2, by2 = [int(v) for v in plate_box]
        cv2.rectangle(image, (bx1, by1), (bx2, by2), BLUE, thick)
    if plate_crop is not None and plate_crop.size:
        inset_w = banner_w
        inset_h = max(1, int(plate_crop.shape[0] * inset_w / max(1, plate_crop.shape[1])))
        if inset_h > height * 0.3:
            inset_h = int(height * 0.3)
            inset_w = max(1, int(plate_crop.shape[1] * inset_h / max(1, plate_crop.shape[0])))
        image[top:top + inset_h, pad:pad + inset_w] = cv2.resize(
            plate_crop, (inset_w, inset_h), interpolation=cv2.INTER_CUBIC)
        cv2.rectangle(image, (pad, top), (pad + inset_w, top + inset_h), BLUE, thick)
        top += inset_h

    banner_h = int(34 * unit)
    rows = 2 + len(extra_lines)
    cv2.rectangle(image, (pad, top), (pad + banner_w, top + rows * banner_h), BLACK, -1)
    draw_text(image, plate_label or "PLATE UNREADABLE",
              (pad + int(8 * unit), top + int(banner_h * 0.8)), 0.85 * unit,
              WHITE if plate_label else RED, thick)
    draw_text(image, second_line, (pad + int(8 * unit), top + int(banner_h * 1.7)),
              0.6 * unit, WHITE, max(1, thick - 1))
    for index, line in enumerate(extra_lines):
        draw_text(image, line, (pad + int(8 * unit), top + int(banner_h * (2.7 + index))),
                  0.55 * unit, WHITE, max(1, thick - 1))
    draw_text(image, footer, (pad, height - pad), 0.6 * unit, WHITE, max(1, thick - 1))
    return image
