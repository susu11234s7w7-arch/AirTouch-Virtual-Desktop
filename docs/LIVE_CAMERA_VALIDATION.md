# Live Camera and Floating Launcher Validation

Automated tests cover the state machine, Qt overlay shape, pinch calibration, cursor mapping, and mocked app launchers. Real camera and desktop behavior must be checked on the target Windows desktop.

## Run the application

From the project root in PowerShell:

```powershell
.\.venv-overlay\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv-overlay\Scripts\python.exe .\main.py
```

The initial Qt window is the mirrored camera preview. Camera capture and MediaPipe run on a dedicated worker and continue after the preview is hidden. The launcher is a separate transparent, frameless, always-on-top PySide6 window; it is not drawn into the camera image. Its window region covers the five app cards and Exit UI, while transparent gaps pass input to the desktop.

## Gesture checks

1. Confirm the camera preview appears and `results/airtouch_sessions/session_*.csv` records `CAMERA_INITIALIZED`.
2. Hold `FIST`. Confirm the preview and launcher hide, the state becomes `DESKTOP_MODE`, and later tracking events continue. Confirm there is no `MINIMIZE_ALL`/Win+D event.
3. Hold `OPEN_PALM`. Confirm the camera preview stays hidden and the translucent topmost app arc appears over the desktop.
4. Use POINTING and confirm the glowing yellow cursor is visible both on and outside the app cards. Verify the native pointer follows it and each card highlights without launching.
5. Hold PINCH over one card. Confirm one native left click selects that app. Keep pinching and verify there is no repeated click until the calibrated pinch is released and deliberately repeated.
6. After an app opens, point at a normal window control such as its close button and pinch once. Confirm the control receives the click.
7. Verify PEACE, UNKNOWN, and tracking loss never issue clicks; on loss the cursor hides and stale coordinates cannot be clicked.
8. Turn the hand from the initial palm-facing pose to show its back and hold. Confirm AirTouch exits only after the orientation change is stable and releases the camera.
9. Use **Exit UI** or the system-tray menu as explicit shutdown fallbacks.
10. Test Chrome, VS Code, Explorer, Edge, and Settings on the Windows installation. A missing app must be reported as `NOT TESTED` rather than counted as success.

The saved empirical PINCH calibration file is loaded by the camera worker and is not changed at runtime. Its one-shot signal gates the left click. The legacy calibration utility remains available.

## Diagnostic mode

`tools/live_camera_diagnostic.py` is retained as a legacy telemetry utility; production interaction runs through `main.py` and the PySide6 worker/overlay path. `tools/benchmark.py` measures the vision path.
