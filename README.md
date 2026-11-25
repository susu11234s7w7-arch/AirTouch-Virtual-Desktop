# 🖐️ AirTouch Virtual Desktop

**AirTouch Virtual Desktop** is a touchless human-computer interaction system that lets you control your Windows PC and launch applications through a **virtual air interface** using only your webcam and hand gestures. Built with **MediaPipe Hand Landmarker** and **OpenCV**, it combines real-time gesture recognition, adaptive stabilization, and an interactive on-screen **Virtual App Dock**.

![AirTouch Virtual Desktop Showcase](docs/images/01_airtouch_virtual_dock.jpg)

---

## 📸 Architecture & Gesture Overview

| Supported Gestures | System Pipeline |
| :---: | :---: |
| ![Supported Gestures](docs/images/02_supported_gestures.jpg) | ![System Pipeline](docs/images/03_system_pipeline.jpg) |

---

## 🚀 Key Features

- **Interactive Virtual Application Dock**: Use your index finger (`POINTING`) with EMA cursor smoothing to hover over virtual buttons (1.0s dwell-click) or perform an instant **Pinch (`PINCH`)** click to launch Windows apps seamlessly:
  - 💻 **VS Code**
  - 📂 **File Explorer**
  - 🧮 **Calculator**
  - 📝 **Notepad**
  - 🖥️ **Show Desktop** (`Win + D`)
  - ❌ **Exit UI** (safely closes the AirTouch window)
- **Scale-Invariant Computer Vision & Real Confidence Scoring**: Normalizes landmark distances relative to palm scale for distance-independent recognition, and computes bounded geometric confidence (`0.62–0.99`) from finger joint angles and pinch ratios.
- **Clean Gesture Recognition**:
  - ✋ **Open Palm** (`OPEN_PALM`)
  - ✊ **Fist** (`FIST`)
  - ✌️ **Peace / Victory Sign** (`PEACE`)
  - ☝️ **Index Pointing** (`POINTING`) — drives the smoothed virtual air cursor
  - 🤏 **Pinch** (`PINCH`) — instant click on the Virtual App Dock
  - 👍 **Thumbs Up** (`THUMBS_UP`) — confirms system readiness
- **Adaptive Gesture Stabilization & EMA Smoothing**: Per-gesture frame/time debouncing plus Exponential Moving Average (`CursorSmoother`) filtering prevent jitter and accidental triggers.
- **Glassmorphic HUD & Action Toast Banners**: Displays real-time FPS, confidence score, stability progress, active controller state, dwell progress rings, and live action confirmation banners.

---

## 📁 Project Structure

```
AirTouch-Virtual-Desktop/
├── docs/
│   ├── images/                       # Project showcase & architecture visuals
│   ├── LIVE_CAMERA_VALIDATION.md     # Real-world test scenarios & dock audit
│   └── PERFORMANCE_REPORT.md         # Engineering audit & latency measurements
├── models/
│   └── hand_landmarker.task          # MediaPipe Hand Landmarker task model
├── results/
│   └── benchmark/                    # Reproducible benchmark CSV outputs
├── tests/
│   ├── test_gesture_integration.py   # Gesture state-machine integration tests
│   ├── test_pinch_calibrator.py      # Hysteresis, cooldown, and calibration tests
│   └── test_virtual_interface.py     # Classifier, dock UI, diagnostic, and benchmark tests
├── tools/
│   ├── benchmark.py                  # Latency & FPS benchmark suite (CSV logging)
│   └── live_camera_diagnostic.py     # Live webcam Telemetry HUD & event logger
├── vision_engine/
│   ├── __init__.py
│   ├── gesture_classifier.py         # Scale-invariant finger & gesture classifier
│   ├── gesture_command_controller.py # Gesture sequence state machine
│   ├── gesture_recognition.py        # Landmark adapter
│   ├── hand_tracker.py               # MediaPipe video landmarker pipeline
│   ├── pinch_calibrator.py           # Hysteresis-based PINCH calibrator
│   └── virtual_interface.py          # Virtual Application Dock & glassmorphic HUD
├── main.py                           # Application entry point & webcam loop
├── windows_command_executor.py       # Win32 API & Windows application launcher
├── requirements.txt                  # Project dependencies
└── README.md
```

---

## 🛠️ Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/susu11234s7w7-arch/AirTouch-Virtual-Desktop.git
cd AirTouch-Virtual-Desktop
```

### 2. Create and Activate a Virtual Environment
```powershell
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 🎮 Running the Application

Start the virtual desktop controller:
```bash
python main.py
```

- Press **`q`**, **`ESC`**, or hover on **`Exit UI`** in the Virtual App Dock to exit.

### Running Tests
```bash
python -m tests.test_gesture_integration
python -m unittest tests/test_virtual_interface.py -v
```

---

## 📜 Supported Gestures & Virtual Controls

| Gesture / Interaction | Action Triggered |
|-----------------------|------------------|
| `OPEN_PALM` ➡️ `FIST` | **Minimize All Windows** (Show Desktop) |
| `PEACE` (armed) | **Launch Visual Studio Code** |
| `POINTING` (1.0s dwell on Dock) | **Launch Selected App** (`VS Code`, `Explorer`, `Calculator`, `Notepad`, `Desktop`, `Exit UI`) |
| `PINCH` (over Dock button) | **Instant Click Launch** on the hovered Virtual Dock app |
| `THUMBS_UP` | **Confirm System Ready** |
| `UNKNOWN` | **Re-arm Controller** for next gesture command |

---

## 📄 License
This project is open source and intended for educational, research, and productivity automation use.
