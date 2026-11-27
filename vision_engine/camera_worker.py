"""Dedicated QThread worker; it is the sole owner of camera and MediaPipe."""

from pathlib import Path
import time
import os

import cv2
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from vision_engine.gesture_recognition import GestureRecognition
from vision_engine.hand_tracker import HandTracker
from vision_engine.pinch_calibrator import PinchCalibrationConfig, PinchCalibrator
from vision_engine.gesture_stabilizer import GESTURE_STABILIZATION, GestureStabilizer
from vision_engine.hand_orientation import HandOrientationDetector
from vision_engine.middle_finger_click import MiddleFingerClickDetector


class CameraWorker(QThread):
    cameraStatus = Signal(bool, str)
    frameUpdate = Signal(object)
    previewFrame = Signal(object)
    logEvent = Signal(str, str)

    def __init__(
        self,
        camera_index=0,
        model_path="models/hand_landmarker.task",
        pinch_config_path="results/benchmark/calibrated_pinch_config.json",
        parent=None,
    ):
        super().__init__(parent)
        self.camera_index = int(camera_index)
        self.model_path = str(model_path)
        self.pinch_config_path = Path(pinch_config_path)

    def run(self):
        camera = None
        tracker = None
        com_initialized = False
        try:
            self.logEvent.emit("CAMERA_WORKER", "thread started; initializing camera owner")
            if os.name == "nt":
                import ctypes

                # DirectShow uses COM. Initialize it explicitly on this worker
                # thread so camera ownership is independent of Qt's UI thread.
                hr = ctypes.windll.ole32.CoInitializeEx(None, 0x0)
                com_initialized = hr >= 0
                self.logEvent.emit(
                    "CAMERA_COM",
                    f"CoInitializeEx hr=0x{hr & 0xFFFFFFFF:08X}",
                )

            self.logEvent.emit("HAND_TRACKER", "creating MediaPipe VIDEO task")
            tracker = HandTracker(model_path=self.model_path)
            self.logEvent.emit("HAND_TRACKER", "MediaPipe VIDEO task ready")
            recognizer = GestureRecognition()
            orientation_detector = HandOrientationDetector()
            middle_click_detector = MiddleFingerClickDetector()
            stabilizer = GestureStabilizer(GESTURE_STABILIZATION)
            pinch_config = (
                PinchCalibrationConfig.load(self.pinch_config_path)
                if self.pinch_config_path.is_file()
                else PinchCalibrationConfig()
            )
            pinch_calibrator = PinchCalibrator(pinch_config)

            self.logEvent.emit(
                "CAMERA_OPENING", f"index={self.camera_index}; backend=CAP_MSMF"
            )
            camera = cv2.VideoCapture(self.camera_index, cv2.CAP_MSMF)
            self.logEvent.emit("CAMERA_OPEN_RESULT", f"opened={camera.isOpened()}")
            if not camera.isOpened():
                self.cameraStatus.emit(False, f"Could not open camera {self.camera_index}")
                return
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cameraStatus.emit(True, "Camera opened")
            self.logEvent.emit("CAMERA_INITIALIZED", "opened=True index=0 requested=1280x720")

            started = time.perf_counter()
            last_raw = None
            last_stable = None
            frame_count = 0
            pinch_pending = False

            while not self.isInterruptionRequested():
                ok, frame = camera.read()
                if not ok:
                    self.logEvent.emit("CAMERA_ERROR", "Frame read returned False")
                    self.cameraStatus.emit(False, "Camera frame read failed")
                    break

                frame = cv2.flip(frame, 1)
                now = time.perf_counter()
                timestamp_ms = int((now - started) * 1000)
                annotated, result = tracker.process(frame, timestamp_ms)
                hands = result.hand_landmarks or []
                landmark_count = len(hands[0]) if hands else 0
                tracking = bool(hands)
                pointer_norm = None
                pinch_active = False
                pinch_clicked = False
                pinch_ratio = None
                middle_click_triggered = False
                middle_press_active = False

                if tracking:
                    hand = hands[0]
                    recognition = recognizer.recognize(hand)
                    raw_gesture = recognition["gesture"]
                    orientation_gesture = orientation_detector.update(
                        hand, raw_gesture
                    )
                    finger_states = recognition.get("finger_states", {})
                    middle_click = middle_click_detector.update(
                        finger_states,
                        tracking_available=True,
                        now=now,
                    )
                    middle_click_triggered = middle_click["click_triggered"]
                    middle_press_active = middle_click["press_active"]
                    if middle_click_triggered:
                        self.logEvent.emit(
                            "MIDDLE_FINGER_TAP",
                            "index cursor click; middle finger raised then lowered",
                        )
                    other_open = any(
                        finger_states.get(name, False)
                        for name in ("middle", "ring", "pinky")
                    )
                    pinch_result = pinch_calibrator.update(
                        hand,
                        now=now,
                        can_click=True,
                        other_fingers_open=other_open,
                    )
                    pinch_active = bool(pinch_result["is_pinching"])
                    pinch_ratio = pinch_result.get("pinch_ratio")
                    pointer_norm = (float(hand[8].x), float(hand[8].y))

                    # The saved empirical calibrator, not the classifier's
                    # fallback ratio, is authoritative for app selection.
                    if orientation_gesture == "BACK_OF_HAND":
                        effective_raw = "BACK_OF_HAND"
                    else:
                        effective_raw = "PINCH" if pinch_active else raw_gesture
                    if (
                        orientation_gesture != "BACK_OF_HAND"
                        and raw_gesture == "PINCH"
                        and not pinch_active
                    ):
                        effective_raw = "UNKNOWN"

                    if pinch_result["click_triggered"]:
                        pinch_pending = True
                    stable = stabilizer.update(effective_raw, now)
                    stable_gesture = stable["stable_gesture"]
                    if stable_gesture == "PINCH" and pinch_pending and pinch_active:
                        pinch_clicked = True
                        pinch_pending = False
                    if not pinch_active:
                        pinch_pending = False
                else:
                    recognizer.recognize(None)
                    middle_click_detector.update(
                        None, tracking_available=False, now=now
                    )
                    pinch_result = pinch_calibrator.update(None, now=now)
                    pinch_pending = False
                    raw_gesture = "UNKNOWN"
                    stable = stabilizer.update("UNKNOWN", now)
                    stable_gesture = stable["stable_gesture"]
                    effective_raw = "UNKNOWN"

                if raw_gesture != last_raw:
                    self.logEvent.emit(
                        "RAW_GESTURE",
                        f"{last_raw} -> {raw_gesture}; effective={effective_raw}",
                    )
                    last_raw = raw_gesture
                if stable_gesture != last_stable:
                    self.logEvent.emit(
                        "STABLE_GESTURE", f"{last_stable} -> {stable_gesture}"
                    )
                    last_stable = stable_gesture

                frame_count += 1
                self.frameUpdate.emit(
                    {
                        "raw_gesture": raw_gesture,
                        "effective_raw": effective_raw,
                        "stable_gesture": stable_gesture,
                        "tracking": tracking,
                        "landmark_count": landmark_count,
                        "pointer_norm": pointer_norm,
                        "pinch_active": pinch_active,
                        "pinch_triggered": pinch_clicked,
                        "pinch_ratio": pinch_ratio,
                        "middle_click_triggered": middle_click_triggered,
                        "middle_press_active": middle_press_active,
                        "elapsed": now - started,
                    }
                )

                # Preview is a UI concern; emitting a copied QImage keeps the
                # MediaPipe-owned buffer out of Qt and does not transfer camera
                # ownership away from this worker.
                if frame_count % 2 == 0:
                    rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
                    height, width, channels = rgb.shape
                    image = QImage(
                        rgb.data,
                        width,
                        height,
                        channels * width,
                        QImage.Format.Format_RGB888,
                    ).copy()
                    self.previewFrame.emit(image)

        except Exception as exc:
            self.cameraStatus.emit(False, f"Camera worker error: {exc}")
            self.logEvent.emit("CAMERA_EXCEPTION", repr(exc))
        finally:
            if camera is not None:
                camera.release()
            if tracker is not None:
                tracker.close()
            if com_initialized:
                import ctypes

                ctypes.windll.ole32.CoUninitialize()
            self.logEvent.emit("CAMERA_RELEASED", "camera and tracker resources released")
            self.cameraStatus.emit(False, "Camera stopped")
