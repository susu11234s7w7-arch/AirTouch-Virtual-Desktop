# AirTouch Virtual Desktop

AirTouch is a Windows hand-gesture controller built with OpenCV, MediaPipe, and PySide6. The camera worker keeps running while the camera preview and desktop launcher are shown or hidden.

## Camera preview and desktop overlay

- **Camera preview:** A separate Qt window shows the mirrored camera image and tracked hand landmarks during monitoring.
- **Windows desktop launcher:** A separate PySide6 frameless, translucent, always-on-top overlay. It is not drawn into the preview. Its shaped window region accepts input only over the app cards and Exit UI control; transparent gaps pass input to desktop windows.
- **Air cursor:** A separate full-screen transparent, click-through layer shows a glowing yellow cursor anywhere on the desktop while POINTING is stable. It also moves the native Windows pointer so clicks can target launcher tiles and normal app controls such as a window's close button.

Camera capture and MediaPipe run on one dedicated worker thread that owns the camera. Qt windows and app-launch callbacks run independently. The saved empirical PINCH calibration is loaded unchanged and gates one left click per deliberate pinch. Hovering only highlights a tile; it never launches an app by itself.

## Gesture controls

| Gesture | Action |
| --- | --- |
| `OPEN_PALM` | Hide the preview and show the floating launcher |
| `POINTING` | Move the smoothed air cursor and highlight any app tile |
| Hover over an app tile | Highlight the tile; does not launch |
| Calibrated `PINCH` while pointing | Send one native left click at the current cursor position |
| Stable physical mouse click | Select the clicked app tile as a fallback |
| `FIST` | Hide the preview and launcher, then enter desktop mode; camera tracking continues without Win+D |
| `PEACE` | No command |
| `UNKNOWN` or tracking loss | Hide the air cursor, cancel hover feedback, and block clicks |
| Turn the hand to show its back | Safely exit AirTouch and release the camera after a stable orientation change |
| Other gestures | No command |

The floating arc contains Google Chrome, Visual Studio Code, File Explorer, Microsoft Edge, and Windows Settings. A successful launch hides the launcher and leaves the camera worker active. Exit UI is available on the launcher and in the system tray.

## Install and run (PowerShell)

From the project root:

```powershell
.\.venv-overlay\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv-overlay\Scripts\python.exe .\main.py
```

The initial window is the camera monitor. FIST hides it without stopping capture; OPEN_PALM displays the floating launcher. While pointing, PINCH clicks at the yellow cursor, including controls in an app window. Use the **Exit UI** control, system-tray menu, or sustained hand flip to close the application and release the camera.

## Tests

```powershell
.\.venv-overlay\Scripts\python.exe -m unittest discover -s .\tests -v
```

The state-machine and Qt-window tests run in the test suite. Real camera gestures, Windows focus changes, overlay appearance, and application launches still require live Windows validation.

## Project layout

```text
vision_engine/
  camera_worker.py               Single-owner camera/MediaPipe QThread worker
  desktop_interaction.py          Desktop launcher state machine and cursor mapping
  qt_floating_launcher.py         Translucent topmost app arc and camera preview
  gesture_stabilizer.py           Debounce stable gesture events
  desktop_overlay.py              Legacy Win32 overlay retained for compatibility
  gesture_command_controller.py  Stable gesture to overlay action mapping
  gesture_classifier.py          Scale-invariant hand gesture classifier
  gesture_recognition.py         MediaPipe landmark adapter
  hand_tracker.py                MediaPipe video pipeline
  pinch_calibrator.py            Calibrated pinch hysteresis and cooldown
  virtual_interface.py            Legacy in-frame renderer retained for unit tests
main.py                           Qt application shell and desktop interaction wiring
tools/live_camera_diagnostic.py   Legacy camera telemetry utility
windows_command_executor.py       Existing Windows application launcher
tests/                            Automated gesture, calibration, and overlay tests
```
