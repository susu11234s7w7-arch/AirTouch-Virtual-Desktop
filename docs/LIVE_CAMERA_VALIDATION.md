# Live Camera Validation & Virtual Dock Verification

**Project:** AirTouch Virtual Desktop  
**Validation Status:** **PENDING USER LIVE HAND TESTING**  
*(Note: Automated checks confirmed webcam index `0` opens and delivers `1280x720` frames, and automated unit/integration/synthetic tests passed; however, human hand scenarios `T01`–`T11` have NOT been executed yet and require a live operator in front of the webcam.)*

---

## 1. How to Run Live Validation Locally

### Step 1: Run Live Camera Diagnostic Mode
```powershell
.\.venv\Scripts\python.exe tools\live_camera_diagnostic.py --no-os-exec
```
- Perform each scenario below while observing the Telemetry HUD (`Raw Gesture` vs `Stable Gesture`, `FPS`, `Frame Time`, `Pinch Ratio`, `Tracking`, `Handedness`).
- Optional empirical `PINCH` calibration during the session:
  1. Hold hand open in `POINTING` / `OPEN_PALM` and press **`O`** at least **10 times**.
  2. Hold `PINCH` clearly and press **`P`** at least **10 times**.
  3. Press **`C`** to compute and save `results/benchmark/calibrated_pinch_config.json`.
- Press **`Q`** or **`ESC`** to stop and save the timestamped CSV log in `results/benchmark/diagnostic_events_<timestamp>.csv`.

### Step 2: Run Live Webcam Performance Benchmark (With Active Hand)
```powershell
.\.venv\Scripts\python.exe tools\benchmark.py --mode webcam --frames 300 --show
```
- Perform steady `POINTING`, `PINCH`, `OPEN_PALM -> FIST`, and `PEACE` gestures during the 300 frames.
- Inspect the generated summary in `results/benchmark/benchmark_sessions.csv`.

---

## 2. Real-World Test Scenarios Matrix (`T01`–`T11`)

| Test ID | Scenario | Expected Result | Actual Result | Pass/Fail | Notes |
|---|---|---|---|---|---|
| **T01** | Strong lighting (bright front/overhead light) | Hand stays `TRACKED`; `OPEN_PALM`, `FIST`, `PEACE`, `POINTING`, `PINCH` classify accurately without flicker | `PENDING_USER_LIVE_RUN` | `PENDING` | Watch for overexposed skin washing out landmarks |
| **T02** | Medium indoor lighting (normal room) | Stable recognition; `Dwell` (1.0s) and `PINCH` trigger reliably with hysteresis holding inside `[0.30, 0.42]` | `PENDING_USER_LIVE_RUN` | `PENDING` | Baseline reference lighting |
| **T03** | Low lighting (dim room / backlit) | Degradation monitored via `Hand Tracking Loss Rate` and `Raw vs Stable` flicker count | `PENDING_USER_LIVE_RUN` | `PENDING` | Expected higher tracking loss or jitter |
| **T04** | Hand close to camera (~30–40 cm) | `palm_scale` normalizes distances; `PINCH` and gestures maintain accuracy | `PENDING_USER_LIVE_RUN` | `PENDING` | Verify hand stays inside frame bounds |
| **T05** | Hand far from camera (~90–120 cm) | `palm_scale` scales down thresholds; `PINCH` still triggers without requiring huge motion | `PENDING_USER_LIVE_RUN` | `PENDING` | Monitor tracking loss at small pixel size |
| **T06** | Fast hand motion | `GestureStabilizer` suppresses transient misclassifications; no unintended Windows commands | `PENDING_USER_LIVE_RUN` | `PENDING` | Observe `Raw != Stable [STABILIZING]` indicator |
| **T07** | Slow deliberate hand motion | `CursorSmoother` glides smoothly; `PINCH` and `Dwell` hit intended Virtual Dock tile accurately | `PENDING_USER_LIVE_RUN` | `PENDING` | Confirm deadzone suppresses micro-tremor |
| **T08** | Hand loss & recovery (move hand out of frame then back) | `Tracking` switches to `LOST`, `PinchCalibrator` resets to `HAND_LOST`, `GestureController` re-arms on `UNKNOWN` | `PENDING_USER_LIVE_RUN` | `PENDING` | Verify no stale cursor jump on re-entry |
| **T09** | Right hand operation | `Handedness` updates in HUD; all gestures & `PINCH` work consistently | `PENDING_USER_LIVE_RUN` | `PENDING` | Note horizontal flip mirrors MediaPipe Left/Right label |
| **T10** | Left hand operation | `Handedness` updates in HUD; thumb extension & `PINCH` rules remain accurate | `PENDING_USER_LIVE_RUN` | `PENDING` | Verify symmetry of `thumb_tip_norm` rule |
| **T11** | Two hands in frame simultaneously | `HandTracker` (`num_hands=2`) draws both hands; controller tracks `hand_landmarks[0]` without crash | `PENDING_USER_LIVE_RUN` | `PENDING` | Check if primary hand switching occurs when crossing |

---

## 3. Phase F — `VirtualAppDock` Architectural Verification

### Verified Finding
Inspection of [main.py](../main.py) (`cv2.imshow(WINDOW_TITLE, annotated)`) and [vision_engine/virtual_interface.py](../vision_engine/virtual_interface.py) (`VirtualAppDock.draw`) confirms:

1. **`VirtualAppDock` is drawn ONLY inside the OpenCV camera frame** (`annotated` BGR buffer).
2. **It lives inside an OpenCV GUI window** (`"AirTouch Virtual Desktop - Hand Control Center"`), **NOT** as an independent Windows transparent desktop overlay (`WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST`).

### Documented Architectural Implications
- Because the dock is bound inside the OpenCV window:
  - Launching any external Windows application (`VS Code`, `Explorer`, `Calculator`, `Notepad`) brings that new app window to the foreground, **covering the OpenCV camera window and hiding `VirtualAppDock`**.
  - Triggering `MINIMIZE_ALL` (`Win + D`) **minimizes the OpenCV window itself**, requiring manual restoration to continue using the dock.
  - Therefore, **AirTouch Virtual Desktop currently provides in-frame camera virtual dock control**, and **must NOT be described as a system-wide transparent desktop overlay**.

### Proposed Future Architectural Solution (Deferred to Later Phase)
- Separate the vision backend (headless webcam + MediaPipe worker thread) from a **transparent always-on-top Win32 / PySide6 layered overlay dock** pinned to the top edge of the Windows screen (`HWND_TOPMOST`), projecting normalized fingertip coordinates `(x, y)` from camera space to screen space so the dock remains visible and interactive above all running Windows applications.
