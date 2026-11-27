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
4. Use POINTING to hover each of the five app cards. Confirm cursor smoothing, hover highlighting, and the `APP_HOVER` state. Hold a tile for 500 ms; it should only become dwell-ready and must not auto-launch.
5. While hovering a tile, PINCH or click its card. Confirm one launch request, a real Windows app window, overlay hide, and continued camera tracking.
6. Keep PINCH held and verify it does not launch twice. Release and re-enter a tile to verify another deliberate selection is accepted after cooldown.
7. Verify PEACE, UNKNOWN, and tracking loss do not launch anything; on loss the cursor and hover clear.
8. Use **Exit UI** or the system-tray menu to stop the camera worker and close the Qt windows.
9. Test Chrome, VS Code, Explorer, Edge, and Settings on the Windows installation. A missing app must be reported as `NOT TESTED` rather than counted as success.

The saved empirical PINCH calibration file is loaded by the camera worker and is not changed at runtime. The legacy calibration utility remains available.

## Diagnostic mode

`tools/live_camera_diagnostic.py` is retained as a legacy telemetry utility; production interaction runs through `main.py` and the PySide6 worker/overlay path. `tools/benchmark.py` measures the vision path.
