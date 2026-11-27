import argparse
from collections import deque
import csv
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import (
    CAMERA_INDEX,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    GESTURE_STABILIZATION,
    MODEL_PATH,
    SEQUENCE_TIMEOUT,
    GestureStabilizer,
    execute_windows_command,
)
from vision_engine.gesture_command_controller import GestureCommandController
from vision_engine.gesture_recognition import GestureRecognition
from vision_engine.hand_tracker import HandTracker
from vision_engine.pinch_calibrator import PinchCalibrationConfig, PinchCalibrator
from vision_engine.desktop_overlay import (
    BackgroundCommandLauncher,
    DesktopOverlayController,
    WindowsDesktopOverlay,
)
from vision_engine.virtual_interface import (
    CursorSmoother,
    _draw_translucent_rect,
)
from windows_command_executor import WindowsCommandExecutor


class DiagnosticEventLog:
    """Timestamped event logger for gesture transitions, pinch states, and commands."""

    def __init__(self, max_display=7):
        self.events = []
        self.recent = deque(maxlen=max_display)
        self.session_start = time.perf_counter()

    def record(self, event_type, detail, now=None):
        now = time.perf_counter() if now is None else now
        elapsed_s = round(max(0.0, now - self.session_start), 4)
        wall_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        entry = {
            "wall_time_utc": wall_iso,
            "elapsed_s": elapsed_s,
            "event_type": event_type,
            "detail": detail,
        }
        self.events.append(entry)
        self.recent.append(f"[{elapsed_s:6.2f}s] {event_type}: {detail}")
        return entry

    def export_csv(self, output_path):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["wall_time_utc", "elapsed_s", "event_type", "detail"]
            )
            writer.writeheader()
            writer.writerows(self.events)
        return path


class DiagnosticPipeline:
    """Single-frame diagnostic coordinator preserving all production interfaces."""

    def __init__(
        self,
        tracker,
        recognizer,
        stabilizer,
        controller,
        cursor_smoother,
        pinch_calibrator,
        executor=None,
        execute_os_commands=True,
        desktop_overlay_controller=None,
        command_launcher=None,
    ):
        self.tracker = tracker
        self.recognizer = recognizer
        self.stabilizer = stabilizer
        self.controller = controller
        self.cursor_smoother = cursor_smoother
        self.pinch_calibrator = pinch_calibrator
        self.executor = executor
        self.execute_os_commands = execute_os_commands
        self.desktop_overlay_controller = desktop_overlay_controller
        self.command_launcher = command_launcher

        self.event_log = DiagnosticEventLog()
        self.start_time = time.perf_counter()
        self.frame_count = 0
        self.fps = 0.0

        self.last_raw_gesture = None
        self.last_stable_gesture = None
        self.last_tracking_status = None
        self.last_overlay_state = None
        self.last_cursor_signature = None
        self.last_geometry_log_at = None
        self.last_pinch_state = None
        self.last_controller_gesture = None

        self.controller_message = "ARMED - waiting for gesture"
        self.last_command_message = "No command executed"
        self.stop_requested = False

        self.last_landmarks = None
        self.last_telemetry = {}

    def _run_command(self, command, source):
        if not self.execute_os_commands or self.executor is None:
            msg = f"[DRY-RUN {source}] {command}"
            self.event_log.record("COMMAND_DRY_RUN", msg)
            return msg

        try:
            result = str(execute_windows_command(self.executor, command))
            self.event_log.record("COMMAND_EXECUTED", f"{source}: {command} -> {result}")
            return result
        except Exception as exc:
            msg = f"Execution Error: {exc}"
            self.event_log.record("COMMAND_ERROR", f"{source}: {command} -> {exc}")
            return msg

    def process_frame(self, frame, now=None):
        frame_start = time.perf_counter() if now is None else now
        timestamp_ms = max(0, int((frame_start - self.start_time) * 1000))

        annotated, result = self.tracker.process(frame, timestamp_ms)
        hands_count = len(result.hand_landmarks) if result.hand_landmarks else 0
        primary_landmark_count = (
            len(result.hand_landmarks[0]) if hands_count > 0 else 0
        )
        tracking_status = "TRACKED" if hands_count > 0 else "LOST"
        handedness = (
            self.tracker.extract_handedness(result, 0)
            if hands_count > 0
            else "N/A"
        )

        tracking_detail = (
            f"{tracking_status} hands={hands_count} "
            f"primary_landmarks={primary_landmark_count}"
        )
        if tracking_detail != self.last_tracking_status:
            self.event_log.record("TRACKING", tracking_detail, now=frame_start)
            self.last_tracking_status = tracking_detail

        raw_pointer_norm = None
        primary_hand = None
        if hands_count > 0:
            primary_hand = result.hand_landmarks[0]
            self.last_landmarks = primary_hand
            recognition = self.recognizer.recognize(primary_hand)
            raw_gesture = recognition["gesture"]
            confidence = recognition["confidence"]
            finger_states = recognition.get("finger_states", {})
            finger_geometry = recognition.get("finger_geometry", {})
            other_open = any(
                finger_states.get(k, False) for k in ("middle", "ring", "pinky")
            )

            if (
                finger_geometry
                and (
                    self.last_geometry_log_at is None
                    or frame_start - self.last_geometry_log_at >= 0.3
                )
            ):
                geometry_detail = "; ".join(
                    f"{name}:pip={m['pip_angle']:.0f},dip={m['dip_angle']:.0f},"
                    f"straight={m['straightness']:.2f},reach={m['normalized_reach']:.2f},"
                    f"score={m['extension_score']:.2f}"
                    for name, m in finger_geometry.items()
                )
                self.event_log.record(
                    "HAND_GEOMETRY",
                    f"raw={raw_gesture}; states={finger_states}; {geometry_detail}",
                    now=frame_start,
                )
                self.last_geometry_log_at = frame_start

            index_tip = primary_hand[8]
            raw_pointer_norm = (float(index_tip.x), float(index_tip.y))
        else:
            self.last_landmarks = None
            recognition = self.recognizer.recognize(None)
            raw_gesture = "UNKNOWN"
            confidence = 0.0
            other_open = False

        if raw_gesture != self.last_raw_gesture:
            self.event_log.record(
                "RAW_GESTURE",
                f"{self.last_raw_gesture} -> {raw_gesture} (conf={confidence:.2f})",
                now=frame_start,
            )
            self.last_raw_gesture = raw_gesture

        stabilization = self.stabilizer.update(raw_gesture, frame_start)
        stable_gesture = stabilization["stable_gesture"]

        if stable_gesture != self.last_stable_gesture:
            self.event_log.record(
                "STABLE_GESTURE",
                f"{self.last_stable_gesture} -> {stable_gesture}",
                now=frame_start,
            )
            self.last_stable_gesture = stable_gesture

        gesture_command = None
        if (
            stabilization["changed"]
            and stable_gesture != self.last_controller_gesture
        ):
            cmd_res = self.controller.process(stable_gesture, now=frame_start)
            self.last_controller_gesture = stable_gesture
            self.controller_message = cmd_res["message"]
            additional_commands = cmd_res.get("additional_commands", ())
            mapping = (
                f"{stable_gesture} -> {cmd_res['command'] or 'NO_COMMAND'}"
                + (
                    f" + {' + '.join(additional_commands)}"
                    if additional_commands
                    else ""
                )
                + f" (executed={cmd_res['executed']}; {cmd_res['message']})"
            )
            self.event_log.record(
                "GESTURE_MAPPING",
                mapping,
                now=frame_start,
            )
            if cmd_res["executed"] and cmd_res["command"] is not None:
                gesture_command = cmd_res["command"]
                if gesture_command not in ("SHOW_OVERLAY", "HIDE_OVERLAY"):
                    self.last_command_message = (
                        self.command_launcher(gesture_command)
                        if self.command_launcher is not None
                        else self._run_command(gesture_command, "GESTURE")
                    )
            for additional_command in additional_commands:
                self.event_log.record(
                    "SYSTEM_COMMAND_REQUESTED",
                    f"{stable_gesture} -> {additional_command}",
                    now=frame_start,
                )
                if self.command_launcher is not None:
                    self.command_launcher(additional_command)
                else:
                    self._run_command(additional_command, "GESTURE")

        pinch_eval = self.pinch_calibrator.update(
            primary_hand,
            now=frame_start,
            can_click=False,
            other_fingers_open=other_open,
        )
        if pinch_eval["state"] != self.last_pinch_state:
            self.event_log.record(
                "PINCH_STATE",
                f"{self.last_pinch_state} -> {pinch_eval['state']} (ratio={pinch_eval['pinch_ratio']})",
                now=frame_start,
            )
            self.last_pinch_state = pinch_eval["state"]

        if self.desktop_overlay_controller is not None:
            # A changing raw gesture cancels dwell before the stabilizer has
            # accepted a new state, preventing launches during transitions.
            frame_gesture = (
                stable_gesture if raw_gesture == stable_gesture else "UNKNOWN"
            )
            overlay_result = self.desktop_overlay_controller.process_frame(
                gesture=frame_gesture,
                pointer_xy=raw_pointer_norm,
                tracking_available=hands_count > 0,
                command=gesture_command,
                now=frame_start,
            )
            overlay_state = self.desktop_overlay_controller.state.value
            if overlay_state != self.last_overlay_state:
                self.event_log.record(
                    "OVERLAY_CONTROLLER_STATE",
                    f"{self.last_overlay_state or 'UNINITIALIZED'} -> {overlay_state}",
                    now=frame_start,
                )
                self.last_overlay_state = overlay_state
            cursor_xy = self.desktop_overlay_controller.cursor_xy
            hovered_id = self.desktop_overlay_controller.hovered_id
            cursor_signature = (cursor_xy is not None, hovered_id)
            if cursor_signature != self.last_cursor_signature:
                self.event_log.record(
                    "AIR_CURSOR_HOVER",
                    f"active={cursor_xy is not None} cursor={cursor_xy} hovered={hovered_id}",
                    now=frame_start,
                )
                self.last_cursor_signature = cursor_signature
            if overlay_result.get("selected"):
                selected_command = overlay_result.get("command")
                if selected_command == "EXIT_APP":
                    self.last_command_message = "Exit requested from native desktop overlay"
                    self.event_log.record("COMMAND_EXIT", self.last_command_message, now=frame_start)
                    self.stop_requested = True
                else:
                    self.last_command_message = str(
                        overlay_result.get("result", "Selection complete")
                    )
                    self.event_log.record(
                        "COMMAND_SELECTED",
                        f"{selected_command}: {self.last_command_message}",
                        now=frame_start,
                    )
            self.stop_requested = self.stop_requested or overlay_result.get(
                "stop_requested", False
            )

        self.frame_count += 1
        elapsed_total = frame_start - self.start_time
        if self.frame_count % 10 == 0 and elapsed_total > 0:
            self.fps = self.frame_count / elapsed_total

        frame_proc_ms = (time.perf_counter() - frame_start) * 1000.0
        if self.fps == 0.0 and frame_proc_ms > 0:
            self.fps = min(60.0, 1000.0 / frame_proc_ms)

        telemetry = {
            "fps": round(self.fps, 1),
            "raw_gesture": raw_gesture,
            "stable_gesture": stable_gesture,
            "raw_vs_stable_diff": raw_gesture != stable_gesture,
            "confidence": confidence,
            "pinch_ratio": pinch_eval["pinch_ratio"],
            "pinch_raw_distance": pinch_eval["raw_distance"],
            "pinch_state": pinch_eval["state"],
            "hysteresis_band": pinch_eval["hysteresis_band"],
            "tracking_status": tracking_status,
            "handedness": handedness,
            "cursor_xy": (
                self.desktop_overlay_controller.cursor_xy
                if self.desktop_overlay_controller is not None
                else None
            ),
            "last_command": self.last_command_message,
            "frame_time_ms": round(frame_proc_ms, 2),
            "stability_text": (
                f"{min(stabilization['candidate_count'], stabilization['required_frames'])}"
                f"/{stabilization['required_frames']}"
            ),
        }
        self.last_telemetry = telemetry
        self._draw_diagnostic_hud(annotated, telemetry)
        return annotated, telemetry

    def _draw_diagnostic_hud(self, frame, t):
        h, w = frame.shape[:2]

        # Left Diagnostic Telemetry HUD (10 required fields + Raw/Stable diff highlight)
        panel_w = min(465, w - 24)
        _draw_translucent_rect(frame, (12, 120), (12 + panel_w, 466), (14, 18, 26), alpha=0.76)
        cv2.rectangle(frame, (12, 120), (12 + panel_w, 466), (0, 200, 255), 1)

        diff_label = " [STABILIZING]" if t["raw_vs_stable_diff"] else " [LOCKED]"
        pinch_str = (
            f"{t['pinch_ratio']:.3f} (raw={t['pinch_raw_distance']:.3f}) | {t['pinch_state']} "
            f"[{t['hysteresis_band'][0]:.2f}/{t['hysteresis_band'][1]:.2f}]"
            if t["pinch_ratio"] is not None
            else f"N/A | {t['pinch_state']}"
        )
        cursor_str = str(t["cursor_xy"]) if t["cursor_xy"] is not None else "N/A"
        track_color = (80, 255, 140) if t["tracking_status"] == "TRACKED" else (80, 110, 255)
        diff_color = (0, 200, 255) if t["raw_vs_stable_diff"] else (120, 255, 160)

        rows = [
            ("DIAGNOSTIC TELEMETRY MODE", (0, 230, 255), 0.58, 2),
            (f"FPS: {t['fps']:.1f}   |   Frame Time: {t['frame_time_ms']:.2f} ms", (220, 240, 255), 0.50, 1),
            (f"Tracking: {t['tracking_status']}   |   Handedness: {t['handedness']}", track_color, 0.50, 1),
            (f"Raw Gesture: {t['raw_gesture']}", (255, 210, 110), 0.54, 1),
            (f"Stable Gesture: {t['stable_gesture']}{diff_label} ({t['stability_text']})", diff_color, 0.54, 2),
            (f"Heuristic Confidence: {t['confidence']:.2f} (not calibrated prob.)", (200, 220, 240), 0.46, 1),
            (f"Pinch: {pinch_str}", (170, 245, 255), 0.45, 1),
            (f"Cursor Coordinates: {cursor_str}", (210, 230, 250), 0.48, 1),
            (f"Last Command: {t['last_command'][:42]}", (120, 255, 140), 0.48, 1),
            ("Hotkeys: [O]=OpenSample [P]=PinchSample [C]=Calibrate [Q]=Quit", (180, 195, 215), 0.43, 1),
        ]

        y = 148
        for text, color, scale, thick in rows:
            cv2.putText(
                frame,
                text,
                (22, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                scale,
                color,
                thick,
                cv2.LINE_AA,
            )
            y += 33

        # Right Timestamped Event Log panel (when wide enough)
        if w >= 920:
            log_x1 = max(panel_w + 24, w - 430)
            _draw_translucent_rect(frame, (log_x1, 120), (w - 12, 370), (14, 18, 26), alpha=0.72)
            cv2.rectangle(frame, (log_x1, 120), (w - 12, 370), (100, 130, 170), 1)
            cv2.putText(
                frame,
                "TIMESTAMPED EVENT LOG",
                (log_x1 + 12, 145),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                (170, 225, 255),
                1,
                cv2.LINE_AA,
            )
            ey = 174
            for line in self.event_log.recent:
                cv2.putText(
                    frame,
                    line[:54],
                    (log_x1 + 12, ey),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.41,
                    (220, 230, 240),
                    1,
                    cv2.LINE_AA,
                )
                ey += 27


def run_diagnostic(
    camera_index=CAMERA_INDEX,
    pinch_config_path=None,
    execute_os_commands=True,
    duration_seconds=None,
    output_dir="results/benchmark",
):
    """Run live webcam diagnostic mode opening only ONE camera."""
    pinch_cfg = (
        PinchCalibrationConfig.load(pinch_config_path)
        if pinch_config_path and Path(pinch_config_path).is_file()
        else PinchCalibrationConfig()
    )

    tracker = None
    camera = None
    pipeline = None
    overlay = None
    overlay_controller = None
    launch_worker = None

    try:
        tracker = HandTracker(model_path=MODEL_PATH)
        recognizer = GestureRecognition()
        stabilizer = GestureStabilizer(GESTURE_STABILIZATION)
        controller = GestureCommandController(sequence_timeout=SEQUENCE_TIMEOUT)
        cursor_smoother = CursorSmoother(alpha=0.38, deadzone_px=1.5)
        pinch_calibrator = PinchCalibrator(config=pinch_cfg)
        executor = WindowsCommandExecutor() if execute_os_commands else None
        overlay = WindowsDesktopOverlay().start()

        def execute_diagnostic_command(command):
            if pipeline is None:
                return "Overlay command ignored before diagnostic startup"
            return pipeline._run_command(command, "BACKGROUND")

        launch_worker = BackgroundCommandLauncher(execute_diagnostic_command)

        overlay_controller = DesktopOverlayController(
            overlay=overlay,
            launch_command=launch_worker.submit,
            screen_size=overlay.screen_size,
        )

        pipeline = DiagnosticPipeline(
            tracker=tracker,
            recognizer=recognizer,
            stabilizer=stabilizer,
            controller=controller,
            cursor_smoother=cursor_smoother,
            pinch_calibrator=pinch_calibrator,
            executor=executor,
            execute_os_commands=execute_os_commands,
            desktop_overlay_controller=overlay_controller,
            command_launcher=launch_worker.submit,
        )

        camera = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        if not camera.isOpened():
            raise RuntimeError(f"Could not open webcam at index {camera_index}")

        camera.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        actual_w = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        pipeline.event_log.record(
            "SESSION_START",
            f"camera={camera_index} res={actual_w}x{actual_h} pinch={pinch_cfg.to_dict()}",
        )
        pipeline.event_log.record(
            "CAMERA_INITIALIZED",
            f"opened={camera.isOpened()} index={camera_index} resolution={actual_w}x{actual_h}",
        )

        start = time.perf_counter()
        while True:
            ok, frame = camera.read()
            if not ok:
                pipeline.event_log.record("CAMERA_ERROR", "Frame read returned False")
                break

            frame = cv2.flip(frame, 1)
            now = time.perf_counter()
            annotated, _ = pipeline.process_frame(frame, now=now)

            cv2.imshow("AirTouch Virtual Desktop - Live Diagnostic Mode", annotated)
            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), 27) or pipeline.stop_requested:
                break
            if key == ord("o") and pipeline.last_landmarks is not None:
                ratio = pinch_calibrator.record_sample("open", pipeline.last_landmarks)
                pipeline.event_log.record("SAMPLE_OPEN", f"ratio={ratio:.4f}")
            elif key == ord("p") and pipeline.last_landmarks is not None:
                ratio = pinch_calibrator.record_sample("pinch", pipeline.last_landmarks)
                pipeline.event_log.record("SAMPLE_PINCH", f"ratio={ratio:.4f}")
            elif key == ord("c"):
                try:
                    new_cfg = pinch_calibrator.calibrate_from_samples(min_samples_per_class=10)
                    save_path = Path(output_dir) / "calibrated_pinch_config.json"
                    new_cfg.save(save_path)
                    pipeline.event_log.record(
                        "CALIBRATED",
                        f"enter={new_cfg.enter_ratio} exit={new_cfg.exit_ratio} saved={save_path}",
                    )
                except ValueError as err:
                    pipeline.event_log.record("CALIBRATION_SKIPPED", str(err))

            if duration_seconds is not None and (now - start) >= duration_seconds:
                break

    finally:
        if overlay_controller is not None:
            overlay_controller.shutdown()
        elif overlay is not None:
            overlay.close()
        if launch_worker is not None:
            launch_worker.close()
        if camera is not None:
            camera.release()
        if tracker is not None:
            tracker.close()
        cv2.destroyAllWindows()

        if pipeline is not None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            log_path = pipeline.event_log.export_csv(
                Path(output_dir) / f"diagnostic_events_{ts}.csv"
            )
            print(f"[Diagnostic] Event log saved to: {log_path}")
            print(f"[Diagnostic] Pinch stats: {pipeline.pinch_calibrator.stats()}")


def main():
    parser = argparse.ArgumentParser(description="AirTouch Live Camera Diagnostic Mode")
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX)
    parser.add_argument("--pinch-config", type=str, default=None)
    parser.add_argument("--no-os-exec", action="store_true", help="Log commands without launching OS apps")
    parser.add_argument("--duration", type=float, default=None, help="Auto-exit after N seconds")
    parser.add_argument("--output-dir", type=str, default="results/benchmark")
    args = parser.parse_args()

    run_diagnostic(
        camera_index=args.camera,
        pinch_config_path=args.pinch_config,
        execute_os_commands=not args.no_os_exec,
        duration_seconds=args.duration,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
