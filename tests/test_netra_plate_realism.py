"""member1/netra/netra_plate_realism.py (no CARLA needed)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "member1" / "netra"))


def _load(monkeypatch, on):
    monkeypatch.setenv("NETRA_PLATE_REAL", "1" if on else "0")
    import netra_plate_realism as m
    return importlib.reload(m)


def _scene(body):
    frame = np.full((120, 200, 3), body, np.uint8)
    warped = np.zeros_like(frame)
    warped[50:62, 70:130] = 250
    mask = np.zeros((120, 200), np.uint8)
    mask[50:62, 70:130] = 255
    return frame, warped, mask


def test_off_by_default_changes_nothing(monkeypatch):
    m = _load(monkeypatch, False)
    frame, warped, mask = _scene(20)
    assert m.match_scene(frame, warped, mask) is warped
    assert m.plate_size_m(1.2, 0.3) == (1.2, 0.3) and m.draw_outline()
    ids = np.zeros((120, 200), np.int32)
    assert m.visible_alpha(mask, ids, 7).max() == 1.0


def test_plate_follows_the_scene_light(monkeypatch):
    m = _load(monkeypatch, True)
    assert m.plate_size_m(1.2, 0.3) == (0.52, 0.12) and not m.draw_outline()
    day = m.match_scene(*_scene(140))[52:60, 80:120].mean()
    night = m.match_scene(*_scene(15))[52:60, 80:120].mean()
    rain = m.match_scene(*_scene(140), rain=1.0)[52:60, 80:120].mean()
    assert 200 < day <= 255
    assert night < 60
    assert rain < day


def test_plate_is_hidden_where_another_car_covers_it(monkeypatch):
    m = _load(monkeypatch, True)
    _, _, mask = _scene(100)
    ids = np.full((120, 200), 7, np.int32)
    ids[:, 100:] = 9                    # another car covers the right half
    a = m.visible_alpha(mask, ids, 7)[..., 0]
    assert a[55, 80] == 1.0 and a[55, 110] == 0.0
