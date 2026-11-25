import time
import cv2

from windows_command_executor import WindowsCommandExecutor
from vision_engine.hand_tracker import HandTracker
from vision_engine.gesture_recognition import GestureRecognition
from vision_engine.gesture_command_controller import GestureCommandController
from vision_engine.virtual_interface import CursorSmoother, VirtualAppDock


# =========================================================
# CONFIGURATION
# =========================================================

MODEL_PATH = "models/hand_landmarker.task"

CAMERA_INDEX = 0
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720

SEQUENCE_TIMEOUT = 3.5

GESTURE_STABILIZATION = {
    "OPEN_PALM": {"frames": 2, "seconds": 0.020},
    "FIST": {"frames": 2, "seconds": 0.020},
    "PEACE": {"frames": 2, "seconds": 0.020},
    "POINTING": {"frames": 2, "seconds": 0.020},
    "PINCH": {"frames": 2, "seconds": 0.015},
    "THUMBS_UP": {"frames": 2, "seconds": 0.020},
    "UNKNOWN": {"frames": 3, "seconds": 0.090},
}

WINDOW_TITLE = "AirTouch Virtual Desktop - Hand Control Center"


# =========================================================
# WINDOWS COMMAND EXECUTOR
# =========================================================

def execute_windows_command(executor, command):
    """Execute only explicitly approved Windows desktop and app commands."""
    allowed_commands = {
        "MINIMIZE_ALL": executor.minimize_all,
        "OPEN_VSCODE": executor.open_vscode,
        "OPEN_EXPLORER": executor.open_explorer,
        "OPEN_CALCULATOR": executor.open_calculator,
        "OPEN_NOTEPAD": executor.open_notepad,
    }

    action = allowed_commands.get(command)
    if action is None:
        raise ValueError(f"Unauthorized command: {command}")

    return action()


# =========================================================
# GESTURE STABILIZER
# =========================================================

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


def _safe_run_command(executor, command):
    """Run an authorized Windows command and return status message."""
    try:
        execution_result = execute_windows_command(executor, command)
        print(f"[EXECUTION RESULT] {execution_result}")
        return str(execution_result)
    except Exception as error:
        message = f"Execution Error: {error}"
        print(f"[EXECUTION ERROR] {error}")
        return message


# =========================================================
# MAIN APPLICATION
# =========================================================

def main():
    tracker = None
    camera = None

    try:
        # 1. Initialize components
        tracker = HandTracker(model_path=MODEL_PATH)
        recognizer = GestureRecognition()
        controller = GestureCommandController(sequence_timeout=SEQUENCE_TIMEOUT)
        executor = WindowsCommandExecutor()
        stabilizer = GestureStabilizer(GESTURE_STABILIZATION)
        cursor_smoother = CursorSmoother(alpha=0.38, deadzone_px=1.5)
        virtual_dock = VirtualAppDock(dwell_seconds=1.0, cooldown_seconds=1.8)

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
        stop_requested = False

        # 4. Startup information
        print("=" * 64)
        print("              AIRTOUCH VIRTUAL DESKTOP CENTER")
        print("=" * 64)
        print("Hand Tracking           : ACTIVE")
        print("Gesture Recognition     : ACTIVE")
        print("Virtual App Dock        : ACTIVE")
        print("Adaptive Stabilization  : ACTIVE")
        print("Command Controller      : ACTIVE")
        print("Windows Executor        : ACTIVE")
        print("-" * 64)
        for gesture, settings in GESTURE_STABILIZATION.items():
            print(
                f"{gesture:16} : "
                f"{settings['frames']} frames / "
                f"{settings['seconds'] * 1000:.0f} ms"
            )
        print("-" * 64)
        print(f"Sequence Timeout        : {SEQUENCE_TIMEOUT:.1f}s")
        print("OPEN_PALM -> FIST       : MINIMIZE_ALL")
        print("PEACE                   : OPEN_VSCODE")
        print("POINTING                : VIRTUAL APP DOCK CURSOR")
        print("PINCH                   : INSTANT VIRTUAL DOCK CLICK")
        print("THUMBS_UP               : CONFIRM READY")
        print("Confirmed UNKNOWN       : RE-ARM")
        print("-" * 64)
        print("Press Q or ESC to exit.")
        print("=" * 64)

        # 5. Main camera loop
        while True:
            success, frame = camera.read()
            if not success:
                print("[ERROR] Camera frame error.")
                break

            frame = cv2.flip(frame, 1)
            now = time.perf_counter()
            timestamp_ms = int((now - start_time) * 1000)

            annotated, result = tracker.process(frame, timestamp_ms)
            hands_count = len(result.hand_landmarks) if result.hand_landmarks else 0

            frame_count += 1
            if frame_count % 10 == 0:
                elapsed_total = now - start_time
                if elapsed_total > 0:
                    fps = frame_count / elapsed_total

            raw_pointer_xy = None
            if hands_count > 0:
                primary_hand = result.hand_landmarks[0]
                recognition = recognizer.recognize(primary_hand)
                raw_gesture = recognition["gesture"]
                confidence = recognition["confidence"]

                index_tip = primary_hand[8]
                raw_pointer_xy = (
                    int(index_tip.x * frame.shape[1]),
                    int(index_tip.y * frame.shape[0]),
                )
            else:
                raw_gesture = "UNKNOWN"
                confidence = 0.0

            pointer_xy = cursor_smoother.update(raw_pointer_xy)
            stabilization = stabilizer.update(raw_gesture, now)
            stable_gesture = stabilization["stable_gesture"]

            if (
                stabilization["changed"]
                and stable_gesture != last_controller_gesture
            ):
                command_result = controller.process(stable_gesture)
                last_controller_gesture = stable_gesture
                controller_message = command_result["message"]

                if (
                    command_result["executed"]
                    and command_result["command"] is not None
                ):
                    detected_command = command_result["command"]
                    print(f"\n[COMMAND DETECTED] {detected_command}")
                    last_command_message = _safe_run_command(
                        executor, detected_command
                    )
                    virtual_dock.show_toast(
                        f"[GESTURE] {last_command_message}",
                        color=(0, 220, 255),
                        now=now,
                    )

            is_pointing = stable_gesture == "POINTING"
            is_pinching = stable_gesture == "PINCH"
            dock_result = virtual_dock.update(
                pointer_xy=pointer_xy,
                is_pointing=is_pointing,
                frame_width=annotated.shape[1],
                is_pinching=is_pinching,
                now=now,
            )

            if dock_result["triggered"] and dock_result["command"]:
                dock_command = dock_result["command"]
                mode = dock_result["trigger_mode"] or "DOCK"
                print(
                    f"\n[VIRTUAL DOCK - {mode}] {dock_result['label']} -> {dock_command}"
                )
                if dock_command == "EXIT_APP":
                    last_command_message = "Exit requested from Virtual Dock"
                    virtual_dock.show_toast(
                        f"[{mode}] Exiting AirTouch UI...",
                        color=(90, 120, 255),
                        now=now,
                    )
                    stop_requested = True
                else:
                    last_command_message = _safe_run_command(
                        executor, dock_command
                    )
                    virtual_dock.show_toast(
                        f"[{mode}] {dock_result['label']} launched",
                        color=(0, 235, 160),
                        now=now,
                    )

            display_gesture = (
                "NO HAND" if stable_gesture == "UNKNOWN" else stable_gesture
            )
            stability_text = (
                f"{min(stabilization['candidate_count'], stabilization['required_frames'])}"
                f"/{stabilization['required_frames']}"
            )

            virtual_dock.draw(
                annotated,
                pointer_xy=pointer_xy,
                is_pointing=is_pointing,
                is_pinching=is_pinching,
                hud_info={
                    "hands_count": hands_count,
                    "fps": fps,
                    "display_gesture": display_gesture,
                    "raw_gesture": raw_gesture,
                    "stability_text": stability_text,
                    "confidence": confidence,
                    "controller_message": controller_message,
                    "last_command_message": last_command_message,
                },
                now=now,
            )

            cv2.imshow(WINDOW_TITLE, annotated)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27) or stop_requested:
                break

    except Exception as error:
        print(f"\n[FATAL ERROR] {error}")

    finally:
        if camera is not None:
            camera.release()
        if tracker is not None:
            tracker.close()
        cv2.destroyAllWindows()
        print("\nAirTouch Virtual Desktop stopped.")
        print("Resources released.")


if __name__ == "__main__":
    main()
