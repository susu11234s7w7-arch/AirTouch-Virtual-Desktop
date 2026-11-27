# AirTouch Virtual Desktop — Audit & Performance Report

**Repository:** `https://github.com/susu11234s7w7-arch/AirTouch-Virtual-Desktop`  
**Audit Baseline Commit:** `6e18f4c` (`main` branch)  
**Benchmark Logs:** `results/benchmark/benchmark_sessions.csv`

> Historical note: the measurements below describe earlier implementations. The current runtime uses a calibrated PINCH or stable tile click to select an app; 500 ms hover is used to mark the APP_HOVER/dwell-ready state and does not launch by itself. See [LIVE_CAMERA_VALIDATION.md](LIVE_CAMERA_VALIDATION.md) for current interaction checks.

---

## 1. Verified Results vs Unverified Assumptions

### ✅ Verified Results (Directly Measured / Executed)
1. **Baseline Regression Suite (Commit `6e18f4c`, pre-edit):**
   - `tests/test_gesture_integration.py`: 5/5 assertions `PASS`.
   - `tests/test_virtual_interface.py`: 7/7 tests `OK` (`0.024s`).
2. **Hardware Webcam Probe (Local Machine, `CAMERA_INDEX=0`, `CAP_DSHOW`):**
   - Webcam opens cleanly (`opened=True`), delivers frames (`640x480` default; `1280x720` when configured), open latency `~409.4 ms`.
3. **Real Webcam Hardware Benchmark (`tools/benchmark.py --mode webcam --frames 30`, no human hand present):**
   - Resolution: `1280x720`
   - Average FPS: `8.36 FPS` (Min: `3.68`, Max: `31.62`)
   - **Camera Capture Latency (`cap.read` + `flip`):** `86.463 ms` avg
   - **Hand Tracking Latency (`HandTracker.process`):** `30.247 ms` avg
   - **Gesture Classification + Stabilizer + Calibrator Latency:** `0.025 ms` avg
   - **End-to-End Frame Processing Time:** `119.521 ms` avg | Median: `98.091 ms` | P95: `223.712 ms`
   - **Hand Tracking Loss Rate:** `100.0%` (expected — no human hand was placed before the camera during the automated run)
   - Gesture Transition Latency / Successful Pinch Selection Rate: `N/A` (0 hand frames)
4. **Deterministic Synthetic Pipeline Benchmark (`tools/benchmark.py --mode synthetic --frames 64`):**
   - Average Hand Tracking Latency (blank `640x480` frame): `22.092 ms`
   - Average Classification + Stabilizer + Calibrator Latency: `0.272 ms`
   - Median End-to-End Latency: `23.657 ms` | P95: `31.190 ms`
   - Hand Tracking Loss Rate (scripted `NO_HAND` blocks = 8/64 frames): `12.5%`
   - Average Gesture Transition Latency: `56.928 ms`
   - False Activation Count (rejected transient spikes): `2`
   - Successful Pinch Selection Rate (scripted dock clicks): `100.0% (2/2)`

### ⚠️ Unverified Assumptions (Require User Live Webcam Session)
- Real human accuracy of `OPEN_PALM`, `FIST`, `PEACE`, `POINTING`, `PINCH`, and `THUMBS_UP` across strong/medium/low lighting (`T01`–`T11`) is **UNVERIFIED** until executed by a human operator.
- Real-world false activation rate and `PINCH` hysteresis comfort (`enter=0.30`, `exit=0.42`) across different hand sizes/distances are **UNVERIFIED** on live human skin/motion blur.
- `GestureClassifier._compute_confidence()` returns a deterministic geometric heuristic (`0.62–0.99`), **NOT** a calibrated statistical probability.

---

## 2. Source Code Audit Findings & Fixes Implemented

| # | Severity | Finding | Root Cause | Fix Implemented |
|---|---|---|---|---|
| 1 | High | MediaPipe `RunningMode.VIDEO` throws `ValueError` if two frames share the same `timestamp_ms` | `int((now - start) * 1000)` can yield equal millisecond integers on fast frames | Added monotonic timestamp guard (`_last_timestamp_ms`) in `HandTracker.process()` |
| 2 | High | `PINCH` lacked hysteresis near `0.36` threshold | Single scalar `PINCH_RATIO_THRESHOLD = 0.36` flips rapidly on boundary noise | Created `PinchCalibrator` (`vision_engine/pinch_calibrator.py`) with `enter_ratio=0.30`, `exit_ratio=0.42`, `min_confirm_frames=2`, `cooldown_seconds=1.8`, and false-activation tracking |
| 3 | Medium | Mixed clock sources between `main.py` (`perf_counter`) and `GestureCommandController` (`monotonic`) | `controller.process(stable_gesture)` omitted `now=now` | Updated `main.py` to pass `now=now` consistently |
| 4 | Medium | `GestureRecognition.recognize(None)` omitted `pinch_ratio`, `pinch_distance`, and `palm_scale` keys | Early return dict had fewer keys than `GestureClassifier.classify()` | Added consistent fallback keys in `GestureRecognition.recognize()` and `pinch_distance` in `GestureClassifier.classify()` |
| 5 | Info | `HandTracker` enabled `num_hands=2` and MediaPipe computed `handedness`, but UI ignored it | `main.py` read only `hand_landmarks[0]` | Added `HandTracker.extract_handedness()` and surfaced `Handedness` + `Tracking Status` in `tools/live_camera_diagnostic.py` |
| 6 | Bottleneck | Real webcam `1280x720` capture latency averaged `86.463 ms` (72% of total frame time) | `CAP_DSHOW` uncompressed / auto-exposure capture overhead at `1280x720` | Documented exact breakdown via `tools/benchmark.py`; kept `main.py` resolution unchanged for compatibility and listed MJPG/640x480 evaluation as a recommendation |

---

## 3. Recommendations & Future Targets *(Not Yet Achieved)*

1. **Reduce Camera Capture Latency (Target `< 33 ms` capture):** Benchmark `cv2.VideoWriter_fourcc(*'MJPG')` or `640x480` capture in `CAP_DSHOW` on the physical webcam to lift end-to-end FPS from `~8.4 FPS` toward `25–30 FPS`.
2. **Empirical Pinch Threshold Calibration:** Run `tools/live_camera_diagnostic.py`, record 10+ Open (`[O]`) and 10+ Pinch (`[P]`) samples with `[C]`, and persist real-hand thresholds.
3. **Native Desktop Overlay (Implemented):** The transparent topmost Win32 dock is separate from the OpenCV preview and remains visible while other apps are focused. Live camera and hover-to-launch validation is still required on the target desktop.
