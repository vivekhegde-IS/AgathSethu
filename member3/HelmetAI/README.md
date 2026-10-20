# HelmetAI

Helmet violation detection with the trained V4 YOLO model, CUDA inference, motorcycle/number-plate association, and RapidOCR.

## Included runtime files

- `app.py`: Flask inference website.
- `templates/index.html`: upload and result page.
- `static/style.css`: website styling.
- `models/helmet_v4_final_best.pt`: trained V4 checkpoint used for inference.
- `requirements.txt`: pinned runtime dependencies.

Datasets, generated labels/previews, runtime uploads, virtual environments, and the unused `yolo11n.pt` checkpoint are intentionally excluded.

## Setup

Use Python 3.14 or a compatible Python version, then create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

`requirements.txt` includes `--ignore-requires-python` because RapidOCR 1.4.4 declares an older Python range, but the pinned package was validated and initialized successfully in the project Python 3.14 environment.

## Run

```powershell
.\.venv\Scripts\python.exe .\app.py
```

Open http://127.0.0.1:5000.

The application prints the selected model and device at startup. CUDA is used automatically when available; otherwise inference falls back to CPU.
