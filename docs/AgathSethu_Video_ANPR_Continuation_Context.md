# AgathSethu — Continuation Context for Video ANPR Evidence Work
## Last updated: 2026-09-04

Use this file as the working context when continuing the AgathSethu project tomorrow. The user wants to continue from exactly where the previous conversation stopped.

---

## 1. Project

Repository/project:
- AgathSethu
- Local workspace is under:
  `C:\Users\vivek\Downloads\major project\major project demo 1\AgathSethu`

Project architecture:
- `member1` — CARLA/IMU/crash/scenarios/ground truth/dataset/camera frames
- `member2` — vehicle detection/tracking/ANPR-related components
- `member3` — RFID, fusion, backend, frontend integration
- `shared` — shared components

IMPORTANT BOUNDARY:
- Current task is ONLY the Level 1 flow:
  `Authority → Routine Violation → Inspection`
- Do NOT modify Member 1.
- Do NOT break or rewrite Member 2's existing implementation.
- Do NOT modify RFID/fusion/collision pipelines.
- Do NOT change unrelated website/backend functionality.
- Test locally first.
- Do NOT push to GitHub unless the user explicitly asks.

---

## 2. Current Goal

The user is adding video-based ANPR evidence to the existing Authority → Routine Violation → Inspection workflow.

Required behavior:

1. Authority uploads an unknown traffic video.
2. Backend processes the uploaded video.
3. Video is sampled intelligently rather than processing every frame.
4. Member 2's trained YOLO number-plate detector is used.
5. The system identifies good plate candidates.
6. RapidOCR is called on the best candidate plate crops.
7. Multiple OCR observations should be combined intelligently.
8. Blurry/misread characters should be resolved using multi-frame/character-level consensus where possible.
9. The final detected registration number should NOT be hardcoded.
10. The system must work with different/unseen videos.
11. Generate evidence:
   - original evidence video / uploaded video evidence
   - best evidence frame
   - cropped best number plate
   - annotated best frame
   - result JSON
12. Display the detected registration number separately in the UI.
13. Target processing time is approximately 15–20 seconds on the user's CPU machine.
14. Accuracy is more important than blindly forcing a result.

Do not claim that 15–20 seconds is guaranteed for arbitrary videos. It is a target to benchmark under defined video constraints.

---

## 3. Hardware / Runtime

User's machine:
- Intel Iris Xe integrated graphics
- No NVIDIA CUDA GPU

Current Python:
- Python 3.14.3
- pip 26.0.1
- PyTorch 2.14.0+cpu
- CUDA available: False
- Ultralytics 8.4.138
- OpenCV 5.0.0
- NumPy 2.4.3
- RapidOCR is installed and imports successfully.

Important:
- CPU-first implementation.
- Do NOT assume CUDA.
- Main performance improvements must come from reducing unnecessary YOLO/OCR work, not from NVIDIA acceleration.

---

## 4. Member 2 ANPR Model

Separate Member 2 repository:
`https://github.com/KaustubhGumaste/NumberplateAI`

Member 2 provided these authoritative integration details:

Trained detector:
`runs/detect/runs/number_plate_detector_fast-2/weights/best.pt`

However, the cloned GitHub repo contained:
`model/number_plate_detector.pt`

The project currently has a copied model at:
`AgathSethu/member3/backend/models/number_plate/number_plate_detector.pt`

The current code successfully loads this model.

Current model test confirmed:
- model exists
- YOLO loads successfully
- task is `detect`

Direct model usage supplied by Member 2:

```python
from ultralytics import YOLO

model = YOLO("runs/detect/runs/number_plate_detector_fast-2/weights/best.pt")

results = model.predict(
    source=frame,
    imgsz=1280,
    conf=0.20,
    max_det=50,
    save=False,
    verbose=False
)
```

Input:
- OpenCV BGR frame
- NumPy `(height, width, 3)`
- recommended `imgsz=1280`
- detection confidence threshold `0.20`

YOLO confidence and OCR confidence are independent:
- YOLO confidence = confidence in plate bounding-box detection.
- OCR confidence = confidence in recognized text.
- Do not blindly average them.

Member 2's OCR stack:
- RapidOCR (`rapidocr_onnxruntime`)
- YOLO detects plate region
- crop/enhancement
- RapidOCR
- Indian plate post-processing/validation

Indian plate format:
- compact: `KA04ET3691`
- displayed: `KA 04 ET 3691`
- general format: `SS NN AA NNNN`
- first two letters must be a valid Indian state/UT code.

---

## 5. Current Backend Structure

Relevant current structure:

```text
AgathSethu/
└── member3/
    └── backend/
        ├── app/
        │   ├── core/
        │   ├── dependencies/
        │   ├── models/
        │   ├── routers/
        │   ├── schemas/
        │   └── services/
        │       ├── __init__.py
        │       ├── user_service.py
        │       └── routine_violation_video/
        │           ├── __init__.py
        │           └── processor.py
        ├── models/
        │   └── number_plate/
        │       └── number_plate_detector.pt
        ├── test_model.py
        ├── test_plate_detection.py
        ├── test_plate_ocr.py
        ├── test_video_anpr.py
        └── test_video_output/
```

There was confusion earlier because two `models` directories existed:
- `backend/app/models/` — application/database models
- `backend/models/number_plate/` — ML model weights

This is NOT inherently wrong. The ML model should remain under:
`backend/models/number_plate/`

The application models should remain under:
`backend/app/models/`

Do NOT move/delete `app/models` just because there is another `models` folder.

The processor currently imports through:
`app.services.routine_violation_video.processor`

That import was eventually confirmed working.

A diagnostic command successfully printed:

```text
Loading YOLO...
YOLO loaded.
Loading RapidOCR...
RapidOCR loaded.
YOLO MODEL: OK
RAPIDOCR: OK
```

The processor's model path now resolves to:

```text
C:\Users\vivek\Downloads\major project\major project demo 1\AgathSethu\member3\backend\models\number_plate\number_plate_detector.pt
```

and the model exists.

---

## 6. Existing Testing Progress

### Earlier successful single-image tests

YOLO successfully detected plate regions.

One test produced:
- Total detections: 2
- output image with two detected plates

RapidOCR was successfully called on a cropped plate.

Example OCR:
```text
Text: DL83EN6047
OCR confidence: 0.8138
```

Another OCR test with preprocessing variants showed:

```text
enlarged: DL (0.6415)
enlarged: DL33EN6047 (0.8050)
grayscale: DL (0.6472)
grayscale: DL03EN6047 (0.8149)
sharpened: DL (0.6457)
sharpened: DL03EN6047 (0.8225)
thresholded: L03EN6047 (0.8768)
thresholded: DL (0.6419)
otsu: L03EN604 (0.8218)
```

This demonstrated that OCR may:
- omit a leading character
- confuse similar characters
- return multiple text boxes
- produce different answers across preprocessing variants.

A later improved test showed:
```text
sharpened: DL3EN6047 confidence=0.8222 valid=True
thresholded: DL3EN6047 confidence=0.8999 valid=True
otsu: DL03EN6047 confidence=0.8132 valid=True
```

Important lesson:
- OCR confidence alone is not enough.
- Character-level/multi-observation consensus is needed.

---

## 7. Current Video Test

Test video:
`member3/backend/test_video.mp4`

Video metadata:
- Frames: 271
- FPS: 30.0
- Resolution: 1606 × 894
- Duration: 9.03 seconds

Current optimized pipeline samples 12 frames for YOLO.

A recent run produced:

```text
Fast YOLO frames: 12
Frames successfully loaded: 12
YOLO 1/12 (frame 0)
...
YOLO 12/12 (frame 270)

Plate candidates: 13
Top candidate frames: [98, 245, 171, 196]
```

RapidOCR was definitely called.

For candidate frame 98:

```text
enhanced:
Raw: LA01AT4521
Normalized: LA01AT4521
Confidence: 0.6207
Valid Indian plate: True

sharpened:
Raw: KA01AT4521
Normalized: KA01AT4521
Confidence: 0.6250
Valid Indian plate: True

thresholded:
No OCR text returned
```

Candidate frame 245:

```text
enhanced:
KAHAT4521
confidence 0.6329
invalid

sharpened:
KAHAT4521
confidence 0.6609
invalid
```

Candidate frame 171:

```text
enhanced:
KAAT452
confidence 0.7775
invalid

sharpened:
KA
confidence 0.5677
+
HAT4521
confidence 0.6157

thresholded:
TAAL51
confidence 0.6152
```

Candidate frame 196:

```text
enhanced:
KA
confidence 0.5505
+
HA4521
confidence 0.5212

sharpened:
HA4521
confidence 0.6525

thresholded:
no text
```

Final result from that run:

```json
{
  "success": true,
  "confirmed": true,
  "plate": "KA 01 AT 4521",
  "plate_compact": "KA01AT4521",
  "detector_confidence": 0.6638,
  "ocr_confidence": 0.625,
  "consensus_count": 1,
  "consensus_total": 11,
  "frame_index": 98,
  "timestamp": 3.267,
  "ocr_variant": "sharpened",
  "processing_time_seconds": 26.359
}
```

Evidence files were produced:
- `evidence_video.mp4`
- `best_frame.jpg`
- `best_plate.jpg`
- `best_frame_annotated.jpg`
- `result.json`

This proves:
- YOLO works.
- RapidOCR works.
- Video sampling works.
- Best frame extraction works.
- Plate crop generation works.
- Evidence video generation works.
- But the selection/consensus logic is still not robust enough.

---

## 8. Critical Accuracy Problem

The current result:

```text
Consensus: 1 / 11
```

was still marked:

```text
Success: True
Confirmed: True
```

This is too permissive.

There were many conflicting OCR observations, and only one exact valid observation for `KA01AT4521`.

The algorithm must NOT automatically mark a plate as confirmed just because one OCR variant passes the Indian plate regex.

Need a stronger decision process:
- group OCR observations by normalized candidate
- align candidates by character position
- account for common OCR confusions
- use detector quality + crop quality + OCR confidence + agreement
- distinguish “best OCR guess” from “high-confidence confirmed plate”
- allow a valid result with low consensus to be returned as unconfirmed rather than falsely confirmed.

---

## 9. Important Non-Hardcoding Requirement

The user explicitly asked whether `KA 01 AT 4521` was hardcoded.

It was NOT hardcoded.

The final answer came from OCR:
`KA01AT4521`

The code can hardcode:
- Indian plate format rules
- valid state/UT prefixes
- OCR character normalization/confusion rules
- thresholds/weights

It must NOT hardcode:
- a particular plate number
- a particular frame number
- a particular video's expected result
- a particular vehicle's location
- a fixed plate crop

The videos will be different and unknown.

---

## 10. Current Performance Problem

The user's target:
- approximately 15–20 seconds

Previous versions:
- ~259 seconds
- ~28 seconds
- ~26.36 seconds
- latest test still around 26+ seconds

The latest architecture is much faster than the original but still needs optimization.

Performance must be improved without sacrificing OCR accuracy.

Current bottleneck is likely:
- CPU YOLO inference at `imgsz=1280`
- multiple OCR preprocessing variants
- RapidOCR calls
- possibly repeated image loading / video seeking
- potentially too many OCR observations.

Do NOT solve performance by simply reducing OCR until accuracy collapses.

Recommended direction:
1. Read/sample frames efficiently.
2. Run YOLO on a limited but sufficiently distributed set of frames.
3. Rank plate candidates.
4. OCR only the strongest candidates.
5. Prefer a small number of high-quality crops.
6. Use a staged OCR strategy:
   - primary crop first
   - only run additional preprocessing variants when necessary
7. Stop early when strong evidence is obtained.
8. Reuse already-loaded frames/crops rather than repeatedly reopening video.
9. Keep CPU-only operation.

Potential target:
- 10–14 YOLO frames depending on video duration/resolution
- 3–4 OCR candidate frames
- 1–2 OCR variants initially
- additional variants only for uncertain candidates
- early stopping when multi-frame agreement is strong

But do not blindly hardcode a fixed number that only works for the current 9-second test. Use adaptive sampling based on video duration and resolution.

---

## 11. Evidence Requirement

The user explicitly wants VIDEO evidence, not just images.

The final processing result should provide:
- the uploaded/original video or a properly accessible evidence copy
- best evidence frame
- cropped plate image
- annotated best frame
- result JSON

The website will eventually display:
- video evidence
- best frame
- cropped plate
- detected number plate text in a separate box
- confidence/evidence metadata

Do not remove the video evidence while optimizing.

---

## 12. Current Code Location

Primary service:
`member3/backend/app/services/routine_violation_video/processor.py`

Test:
`member3/backend/test_video_anpr.py`

The user has repeatedly asked for COMPLETE replacement code rather than partial snippets.

When changing either file:
- provide the full file content
- do not give incomplete fragments
- explain exactly which file to replace
- give the exact command to run
- give expected output
- do not modify unrelated files unless necessary.

---

## 13. Current Processor Requirements

The processor should expose something equivalent to:

```python
process_video(video_path, output_dir=...)
```

and return a dictionary containing enough information for the test and future API/UI integration.

At minimum:
- success
- confirmed
- plate
- plate_compact
- detector_confidence
- ocr_confidence
- frame_index
- timestamp
- OCR variant
- processing time
- video metadata
- evidence paths
- result JSON path

If no reliable plate is found:
- return a structured failure result
- do not crash
- do not invent a plate.

The processor should remain importable with:

```python
from app.services.routine_violation_video.processor import process_video
```

---

## 14. Current Test Script Requirements

`test_video_anpr.py` should:
- locate the project/backend
- use the test video
- call `process_video`
- print readable progress
- print final JSON
- verify evidence files exist
- NOT contain a hardcoded expected plate number
- NOT alter the actual processor result.

It is acceptable for the test video path itself to be configurable/defaulted to `test_video.mp4`, but the expected plate must never be hardcoded.

---

## 15. Important Design Direction for Next Session

Next task should be to create a better processor version with:

### A. Adaptive frame sampling
Sample frames distributed across the video rather than every frame.

Example concept:
- determine target sample count from duration
- include beginning/middle/end
- avoid duplicate/near-duplicate frames
- keep frame indices.

### B. Candidate quality scoring
For each detected plate:
- YOLO confidence
- plate area relative to frame
- sharpness (variance of Laplacian)
- boundary/visibility quality
- aspect ratio
- location validity

Use these to rank candidates.

### C. Two-stage OCR
Instead of running every preprocessing variant on every candidate:

Stage 1:
- crop
- resize/enhance
- RapidOCR

If Stage 1 is strong and agrees with another observation, stop.

Stage 2 only when uncertain:
- sharpened
- thresholded/Otsu
- possibly grayscale

### D. OCR result assembly
RapidOCR can return multiple boxes:
```text
KA
HA4521
```

The system should join text observations intelligently when they belong to the same plate crop.

### E. Character-level consensus
For candidates like:
```text
LA01AT4521
KA01AT4521
KAHAT4521
KAAT452
KA + HA4521
```

derive the strongest supported character sequence instead of selecting only the highest OCR confidence.

Important:
- do not simply use Levenshtein distance without considering Indian plate structure.
- compare positions based on:
  `SS NN AA NNNN`
- tolerate missing/blurred characters.
- use OCR confidence and observation quality.

### F. Confidence/confirmation policy
Return:
- `confirmed=True` only when evidence is sufficiently strong.
- Otherwise return the best candidate with `confirmed=False` or `success=False`, depending on policy.

Do not label `1/11` consensus as high-confidence confirmation.

### G. Evidence synchronization
The selected best frame must correspond to the crop/plate observation used to determine the final plate.

---

## 16. Potential Character Confusion Rules

Use these carefully; do not force replacements blindly.

Common OCR confusions may include:
- O ↔ 0
- I ↔ 1
- Z ↔ 2
- S ↔ 5
- B ↔ 8
- G ↔ 6
- D ↔ 0
- L ↔ 1
- T ↔ 7
- A ↔ 4

But replacement must depend on expected position:
- state prefix positions are letters
- district positions are digits
- series positions are letters
- final four positions are digits

Example:
- `LA01AT4521` vs `KA01AT4521`
  should not blindly choose `KA` just because KA is a valid state.
- It should use observations and positional/visual evidence.
- Valid-state information can be a prior/validation signal, not a hardcoded answer.

---

## 17. What NOT to Do

Do NOT:
- hardcode `KA01AT4521`
- hardcode frame 98
- hardcode the current video's plate
- assume every video has the same plate layout
- process all 271 frames with YOLO
- run 5–10 OCR variants on every candidate
- require CUDA
- copy the entire NumberplateAI Flask application into AgathSethu
- replace the existing website
- replace Member 1 or Member 2
- delete `app/models`
- confuse `app/models` with `backend/models/number_plate`
- remove evidence video generation
- mark a result confirmed based on one weak OCR observation
- integrate into frontend until backend testing is reliable.

---

## 18. Immediate Next Step Tomorrow

Start by reviewing the current `processor.py` and `test_video_anpr.py`.

Then replace them with a single coherent optimized version that:
- uses the existing model
- actually calls RapidOCR
- produces evidence video/frame/crop
- performs multi-frame OCR
- performs character-level consensus
- does not hardcode plate values
- aims for 15–20 seconds on this CPU
- handles unknown videos
- gives structured output.

Then run:

```powershell
cd "C:\Users\vivek\Downloads\major project\major project demo 1\AgathSethu\member3\backend"
python test_video_anpr.py
```

Expected successful output should contain:
- model loaded
- RapidOCR loaded
- sampled frames
- YOLO detections
- OCR calls
- OCR observations
- final plate if sufficiently reliable
- confirmation status
- processing time
- evidence video path
- best frame path
- best plate path
- annotated frame path
- result JSON path

After testing, inspect:
- `best_frame.jpg`
- `best_plate.jpg`
- `best_frame_annotated.jpg`
- `evidence_video.mp4`
- `result.json`

Only after this works reliably should the next task be connecting it to the existing Authority → Routine Violation → Inspection frontend.

---

## 19. User Preference for Continuation

The user prefers:
- exact step-by-step instructions
- complete code when asked for code
- exact file paths
- expected output after each step
- no unnecessary changes
- no vague instructions
- accuracy over agreement
- local testing before GitHub push.

When debugging:
- explain what an error actually means
- give the exact correction
- do not assume success
- ask for terminal output/screenshots when required.

---

## 20. Current State Summary

At the end of the last session:
- YOLO model loading: WORKING
- RapidOCR import/loading: WORKING
- YOLO plate detection on video: WORKING
- RapidOCR calls on candidate crops: WORKING
- Evidence video generation: WORKING in the latest successful run
- Best frame extraction: WORKING
- Best plate crop: WORKING
- Annotated best frame: WORKING
- JSON result: WORKING
- Unknown-video support: intended, no plate hardcoding
- Current accuracy: NOT YET ROBUST
- Current processing time: ~26 seconds on test video, needs further optimization toward 15–20 sec
- Current consensus logic: TOO WEAK; must be improved
- Frontend integration: NOT YET DONE
- GitHub push: NOT DONE / should not be done until user explicitly requests it.

Continue from this exact state.
