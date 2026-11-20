import cv2
import time

from windows_command_executor import WindowsCommandExecutor
from vision_engine.hand_tracker import HandTracker
from vision_engine.gesture_recognition import GestureRecognition
from vision_engine.gesture_command_controller import GestureCommandController


# =========================================================
# CONFIGURATION
# =========================================================

MODEL_PATH = "models/hand_landmarker.task"
CAMERA_INDEX = 0
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720

SEQUENCE_TIMEOUT = 3.5

# Each gesture has independent frame and time thresholds.
GESTURE_STABILIZATION = {
    "OPEN_PALM": {"frames": 2, "seconds": 0.020},
    "FIST":      {"frames": 2, "seconds": 0.020},
    "PEACE":     {"frames": 2, "seconds": 0.020},
    "UNKNOWN":   {"frames": 3, "seconds": 0.090},
}

WINDOW_TITLE = "AI Vision Control Center - Live Commands"


def execute_windows_command(executor, command):
    """Execute only explicitly approved Windows commands."""
    allowed_commands = {
        "MINIMIZE_ALL": executor.minimize_all,
        "OPEN_VSCODE": executor.open_vscode,
    }

    action = allowed_commands.get(command)
    if action is None:
        raise ValueError(f"Unauthorized command: {command}")

    return action()


class GestureStabilizer:
    """Per-gesture debounce that ignores brief classification flicker."""

    def __init__(self, settings):
        self.settings = settings
        self.candidate = "UNKNOWN"
        self.candidate_count = 0
        self.candidate_since = None
        self.stable_gesture = "UNKNOWN"

    def update(self, raw_gesture, now):
        raw_gesture = (
            raw_gesture.strip().upper()
            if isinstance(raw_gesture, str)
            else "UNKNOWN"
        )

        if raw_gesture not in self.settings:
            raw_gesture = "UNKNOWN"

        if raw_gesture == self.candidate:
            if self.candidate_since is None:
                self.candidate_since = now
            self.candidate_count += 1
        else:
            self.candidate = raw_gesture
            self.candidate_count = 1
            self.candidate_since = now

        threshold = self.settings[raw_gesture]
        elapsed = (
            now - self.candidate_since
            if self.candidate_since is not None
            else 0.0
        )

        accepted = (
            self.candidate_count >= threshold["frames"]
            and elapsed >= threshold["seconds"]
        )

        changed = False
        if accepted and self.stable_gesture != self.candidate:
            self.stable_gesture = self.candidate
            changed = True

        return {
            "stable_gesture": self.stable_gesture,
            "changed": changed,
            "candidate": self.candidate,
            "candidate_count": self.candidate_count,
            "required_frames": threshold["frames"],
            "elapsed": elapsed,
        }


def main():
    tracker = None
    camera = None

    try:
        # 1. Initialize components
        tracker = HandTracker(model_path=MODEL_PATH)
        recognizer = GestureRecognition()
        controller = GestureCommandController(
            sequence_timeout=SEQUENCE_TIMEOUT
        )
        executor = WindowsCommandExecutor()
        stabilizer = GestureStabilizer(GESTURE_STABILIZATION)

        # 2. Initialize camera
        camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
        if not camera.isOpened():
            raise RuntimeError("Could not open webcam")

        camera.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # 3. Application state
        start_time = time.perf_counter()
        frame_count = 0
        fps = 0.0

        raw_gesture = "UNKNOWN"
        stable_gesture = "UNKNOWN"
        confidence = 0.0

        controller_message = "ARMED - waiting for gesture"
        last_command_message = "No command executed"
        last_controller_gesture = None

        print("=" * 64)
        print("                 AI VISION CONTROL CENTER")
        print("=" * 64)
        print("Hand Tracking           : ACTIVE")
        print("Gesture Recognition     : ACTIVE")
        print("Adaptive Stabilization : ACTIVE")
        print("Command Controller      : ACTIVE")
        print("Windows Executor        : ACTIVE")
        print("-" * 64)

        for gesture, settings in GESTURE_STABILIZATION.items():
            print(
                f"{gesture:12} : {settings['frames']} frames / "
                f"{settings['seconds'] * 1000:.0f} ms"
            )

        print("-" * 64)
        print(f"Sequence Timeout        : {SEQUENCE_TIMEOUT:.1f}s")
        print("OPEN_PALM -> FIST       : MINIMIZE_ALL")
        print("PEACE                   : OPEN_VSCODE")
        print("Confirmed UNKNOWN      : RE-ARM")
        print("-" * 64)
        print("LIVE WINDOWS COMMANDS ENABLED")
        print("Press Q or ESC to exit.")
        print("=" * 64)

        # 4. Main camera loop
        while True:
            success, frame = camera.read()

            if not success:
                print("[ERROR] Camera frame error.")
                break

            frame = cv2.flip(frame, 1)
            now = time.perf_counter()
            timestamp_ms = int((now - start_time) * 1000)

            # Hand tracking
            annotated, result = tracker.process(
                frame,
                timestamp_ms
            )

            hands_count = (
                len(result.hand_landmarks)
                if result.hand_landmarks
                else 0
            )

            # FPS
            frame_count += 1

            if frame_count % 10 == 0:
                elapsed_total = now - start_time

                if elapsed_total > 0:
                    fps = frame_count / elapsed_total

            # Raw gesture recognition
            if hands_count > 0:
                recognition = recognizer.recognize(
                    result.hand_landmarks[0]
                )

                raw_gesture = recognition["gesture"]
                confidence = recognition["confidence"]

            else:
                raw_gesture = "UNKNOWN"
                confidence = 0.0

            # Adaptive stabilization
            stabilization = stabilizer.update(
                raw_gesture,
                now
            )

            stable_gesture = stabilization["stable_gesture"]

            # Process only stable state transitions.
            if (
                stabilization["changed"]
                and stable_gesture != last_controller_gesture
            ):
                command_result = controller.process(
                    stable_gesture
                )

                last_controller_gesture = stable_gesture
                controller_message = command_result["message"]

                # Live Windows execution
                if (
                    command_result["executed"]
                    and command_result["command"] is not None
                ):
                    detected_command = command_result["command"]

                    print(
                        f"\n[COMMAND DETECTED] {detected_command}"
                    )

                    try:
                        execution_result = execute_windows_command(
                            executor,
                            detected_command
                        )

                        last_command_message = str(execution_result)

                        print(
                            f"[EXECUTION RESULT] {execution_result}"
                        )

                    except Exception as error:
                        last_command_message = (
                            f"Execution Error: {error}"
                        )

                        print(
                            f"[EXECUTION ERROR] {error}"
                        )

            # Display
            display_gesture = (
                "NO HAND"
                if stable_gesture == "UNKNOWN"
                else stable_gesture
            )

            stability_text = (
                f"{min(stabilization['candidate_count'], stabilization['required_frames'])}"
                f"/{stabilization['required_frames']}"
            )

            cv2.putText(
                annotated,
                "AI VISION CONTROL CENTER",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

            cv2.putText(
                annotated,
                f"Hands: {hands_count}",
                (20, 75),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2
            )

            cv2.putText(
                annotated,
                f"Gesture: {display_gesture}",
                (20, 115),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 0),
                2
            )

            cv2.putText(
                annotated,
                f"Raw Gesture: {raw_gesture}",
                (20, 155),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 200, 0),
                2
            )

            cv2.putText(
                annotated,
                f"Stability: {stability_text}",
                (20, 195),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 200, 0),
                2
            )

            cv2.putText(
                annotated,
                f"Confidence: {confidence:.2f}",
                (20, 235),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 0),
                2
            )

            cv2.putText(
                annotated,
                f"FPS: {fps:.1f}",
                (20, 275),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 0),
                2
            )

            cv2.putText(
                annotated,
                f"Controller: {controller_message[:48]}",
                (20, 315),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 200, 255),
                2
            )

            cv2.putText(
                annotated,
                last_command_message[:65],
                (20, 355),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 0),
                2
            )

            cv2.putText(
                annotated,
                "MODE: LIVE WINDOWS CONTROL",
                (20, 395),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 165, 255),
                2
            )

            cv2.imshow(WINDOW_TITLE, annotated)

            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), 27):
                break

    except Exception as error:
        print(f"\n[FATAL ERROR] {error}")

    finally:
        if camera is not None:
            camera.release()

        if tracker is not None:
            tracker.close()

        cv2.destroyAllWindows()

        print("\nAI Vision Control Center stopped.")
        print("Resources released.")


if __name__ == "__main__":
    main()