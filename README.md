# 🖐️ AI-Vision-Control

**AI-Vision-Control** is a real-time computer vision system that lets you control your Windows desktop using hand gestures via your webcam. Powered by **MediaPipe Hand Landmarker** and **OpenCV**, it detects gestures, stabilizes detection to prevent flickering, and triggers native Windows commands seamlessly.

---

## 🚀 Features

- **Real-Time Hand Tracking**: Uses Google MediaPipe Hand Landmarker with 21 3D landmarks.
- **Robust Gesture Recognition**: Recognizes gestures such as:
  - ✋ **Open Palm**
  - ✊ **Fist**
  - ✌️ **Peace / Victory Sign**
- **Gesture Stabilization & Debounce**: Frame and time thresholds to avoid erratic triggers and classification jitter.
- **Safe Command Execution**:
  - `OPEN_PALM` -> `FIST`: **Minimize All Windows** (`Win + D` desktop toggle).
  - `UNKNOWN` -> `PEACE`: **Launch Visual Studio Code**.
- **Visual Feedback HUD**: Real-time bounding boxes, landmark tracking, FPS monitor, and command notification banners.

---

## 📁 Project Structure

```
AI-Vision-Control/
├── models/
│   └── hand_landmarker.task         # MediaPipe Hand Landmarker task model
├── tests/
│   └── test_gesture_integration.py  # Gesture controller integration tests
├── vision_engine/
│   ├── __init__.py
│   ├── gesture_classifier.py        # Rule-based finger state & gesture classifier
│   ├── gesture_command_controller.py# Gesture sequence state machine
│   ├── gesture_recognition.py       # Landmark adapter
│   └── hand_tracker.py              # MediaPipe video landmarker pipeline
├── main.py                          # Application entry point & webcam loop
├── windows_command_executor.py      # Win32 desktop API command execution
├── requirements.txt                 # Project dependencies
└── README.md
```

---

## 🛠️ Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/susu11234s7w7-arch/AI-Vision-Control.git
cd AI-Vision-Control
```

### 2. Create and Activate a Virtual Environment
```bash
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

Run the main application:
```bash
python main.py
```

- Press **`q`** or **`ESC`** in the camera window to quit.

### Running Tests
```bash
python -m tests.test_gesture_integration
```

---

## 📜 Supported Gesture Sequences

| Sequence / Gesture | Action Triggered |
|--------------------|------------------|
| `OPEN_PALM` ➡️ `FIST` | **Minimize All Windows** (Show Desktop) |
| `UNKNOWN` ➡️ `PEACE` | **Open Visual Studio Code** |

---

## 📄 License
This project is open source and available under the [MIT License](LICENSE).
