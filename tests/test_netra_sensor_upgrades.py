"""Pure parts of member1/netra/netra_sensor_upgrades.py (no CARLA needed)."""
from __future__ import annotations

import csv
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "member1" / "netra"))


def _load(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import netra_sensor_upgrades as m
    return importlib.reload(m)


def test_everything_off_by_default(tmp_path, monkeypatch):
    for k in ("NETRA_BOX_LOG", "NETRA_FRAME_INDEX", "NETRA_WEATHER"):
        monkeypatch.delenv(k, raising=False)
    m = _load(monkeypatch)
    sent = []
    bl = m.BoxLogger(str(tmp_path), SimpleNamespace(publish=sent.append))
    bl.log(1.0, 20, 2, [{"vehicle_id": "B", "bbox": [1, 2, 30, 40], "depth_m": 20.0}])
    m.FrameIndex(str(tmp_path)).log(1, 20, 1.0)
    assert sent == [] and not list(tmp_path.iterdir())


def test_box_log_writes_and_publishes(tmp_path, monkeypatch):
    m = _load(monkeypatch, NETRA_BOX_LOG="1", NETRA_FRAME_INDEX="1")
    sent = []
    bl = m.BoxLogger(str(tmp_path), SimpleNamespace(publish=sent.append))
    boxes = [{"vehicle_id": "B", "bbox": [1, 2, 30, 40], "depth_m": 20.0, "visible_fraction": 0.7}]
    bl.log(1.25, 25, 2, boxes)
    bl.close()
    rows = list(csv.DictReader(open(tmp_path / "vehicle_boxes.csv", encoding="utf-8")))
    assert rows[0]["junction_id"] == "J02" and rows[0]["vehicle_id"] == "B" and rows[0]["visible_fraction"] == "0.7"
    assert sent[0]["type"] == "vehicle_boxes" and sent[0]["camera_id"] == "CAM_J02_01" and sent[0]["vehicles"] == boxes
    fi = m.FrameIndex(str(tmp_path))
    fi.log(1, 100, 5.0)
    fi.log(1, 101, 5.05)
    fi.close()
    idx = list(csv.reader(open(tmp_path / "camera_frames_index.csv", encoding="utf-8")))
    assert idx[1] == ["J01", "0", "100", "5.000000"] and idx[2][1] == "1"


def test_visible_fraction_from_instance_ids(monkeypatch):
    m = _load(monkeypatch)
    ids = np.zeros((10, 10), np.int32)
    ids[0:5, 0:10] = 300            # vehicle with actor id 300 fills the top half
    out = m.add_visible_fraction([{"vehicle_id": "A", "bbox": [0, 0, 9, 9]}], ids, {"A": 300})
    assert out[0]["visible_fraction"] == 0.5 and out[0]["visible_pixels"] == 50
    raw = np.zeros((2, 2, 4), np.uint8)
    raw[0, 0, 1], raw[0, 0, 0] = 44, 1              # G=44, B=1 -> id 44 + 256
    img = SimpleNamespace(raw_data=raw.tobytes(), height=2, width=2)
    assert m.instance_ids(img)[0, 0] == 300
