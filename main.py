"""AI Vision Control Center with background camera and floating Qt launcher."""

import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QObject, Qt, Signal, Slot, QThread
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QStyle,
    QSystemTrayIcon,
)

from vision_engine.camera_worker import CameraWorker
from vision_engine.air_mouse import left_click, move_system_cursor
from vision_engine.desktop_interaction import (
    DesktopInteractionStateMachine,
    InteractionMode,
)
from vision_engine.gesture_stabilizer import GESTURE_STABILIZATION, GestureStabilizer
from vision_engine.qt_floating_launcher import (
    AirCursorWindow,
    CameraPreviewWindow,
    FloatingLauncherWindow,
)
from windows_command_executor import WindowsCommandExecutor


MODEL_PATH = "models/hand_landmarker.task"
CAMERA_INDEX = 0
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
SEQUENCE_TIMEOUT = 3.5
PINCH_CONFIG_PATH = "results/benchmark/calibrated_pinch_config.json"
WINDOW_TITLE = "AirTouch Virtual Desktop - Camera Monitoring"


def execute_windows_command(executor, command):
    """Execute only explicitly approved Windows app commands."""
    allowed_commands = {
        "MINIMIZE_ALL": executor.minimize_all,
        "OPEN_CHROME": executor.open_chrome,
        "OPEN_VSCODE": executor.open_vscode,
        "OPEN_EXPLORER": executor.open_explorer,
        "OPEN_EDGE": executor.open_edge,
        "OPEN_SETTINGS": executor.open_settings,
        "OPEN_CALCULATOR": executor.open_calculator,
        "OPEN_NOTEPAD": executor.open_notepad,
    }
    action = allowed_commands.get(command)
    if action is None:
        raise ValueError(f"Unauthorized command: {command}")
    return action()


class SessionEventLog:
    """Flush each runtime event to CSV so a live session is auditable."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.started = time.perf_counter()
        self._stream = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._stream,
            fieldnames=("wall_time_utc", "elapsed_s", "event_type", "detail"),
        )
        self._writer.writeheader()
        self._stream.flush()

    def record(self, event_type, detail):
        self._writer.writerow(
            {
                "wall_time_utc": datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds"
                ),
                "elapsed_s": round(time.perf_counter() - self.started, 4),
                "event_type": str(event_type),
                "detail": str(detail),
            }
        )
        self._stream.flush()

    def close(self):
        if not self._stream.closed:
            self._stream.flush()
            self._stream.close()


class ApplicationCommandWorker(QObject):
    """Launch Windows apps away from both the camera and UI threads."""

    launchRequested = Signal(str)
    completed = Signal(str, bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.executor = None

    @Slot(str)
    def execute(self, command):
        try:
            if self.executor is None:
                self.executor = WindowsCommandExecutor()
            message = str(execute_windows_command(self.executor, command))
            success = not message.endswith("_NOT_FOUND")
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            success = False
        self.completed.emit(command, success, message)


class AirTouchController(QObject):
    """Connect Qt windows to the camera worker and explicit state machine."""

    def __init__(self, app, screen_geometry, parent=None):
        super().__init__(parent)
        self.app = app
        self.screen_geometry = screen_geometry
        self.state_machine = DesktopInteractionStateMachine(
            (screen_geometry.width(), screen_geometry.height()),
            cooldown_seconds=1.8,
            dwell_seconds=0.5,
        )
        session_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.log = SessionEventLog(
            Path("results") / "airtouch_sessions" / f"session_{session_stamp}.csv"
        )
        self.preview = CameraPreviewWindow()
        self.launcher = FloatingLauncherWindow(screen_geometry)
        self.air_cursor = AirCursorWindow(screen_geometry)
        self.preview.show()
        self.preview.raise_()
        self.preview.activateWindow()

        self.last_mode = self.state_machine.mode
        self.last_tracking = None
        self.last_hover = None
        self.last_stable_gesture = None
        self.last_middle_press_active = False
        self.is_shutting_down = False

        self.launcher.appSelected.connect(self._on_mouse_selection)
        self.launcher.exitRequested.connect(self.shutdown)

        self._create_tray_menu()
        self.command_thread = QThread(self)
        self.command_worker = ApplicationCommandWorker()
        self.command_worker.moveToThread(self.command_thread)
        self.command_worker.launchRequested.connect(
            self.command_worker.execute,
            Qt.ConnectionType.QueuedConnection,
        )
        self.command_worker.completed.connect(self._on_launch_completed)
        self.command_thread.start()

        self.camera_worker = CameraWorker(
            camera_index=CAMERA_INDEX,
            model_path=MODEL_PATH,
            pinch_config_path=PINCH_CONFIG_PATH,
        )
        self.camera_worker.cameraStatus.connect(self._on_camera_status)
        self.camera_worker.frameUpdate.connect(self._on_frame_update)
        self.camera_worker.previewFrame.connect(self.preview.set_frame)
        self.camera_worker.logEvent.connect(self._log_worker_event)
        self.log.record("SESSION_START", "mode=MONITORING; launcher=hidden")
        self.camera_worker.start()

    def _create_tray_menu(self):
        self.tray = QSystemTrayIcon(
            QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
            self,
        )
        self.tray.setToolTip("AI Vision Control Center is monitoring in background")
        menu = QMenu()
        exit_action = QAction("Exit UI", menu)
        exit_action.triggered.connect(self.shutdown)
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    @Slot(bool, str)
    def _on_camera_status(self, opened, message):
        self.log.record("CAMERA_STATUS", f"opened={opened}; {message}")
        if opened:
            self.preview.set_message("Camera open — monitoring gestures")
            if self.state_machine.mode == InteractionMode.MONITORING:
                self.preview.show()
                self.preview.raise_()
            return
        if message != "Camera stopped" and not self.is_shutting_down:
            self.preview.set_message(message)
            QMessageBox.critical(None, "AirTouch camera error", message)
            self.shutdown()

    @Slot(str, str)
    def _log_worker_event(self, event_type, detail):
        self.log.record(event_type, detail)

    @Slot(object)
    def _on_frame_update(self, frame):
        tracking = bool(frame["tracking"])
        if tracking != self.last_tracking:
            self.last_tracking = tracking
            self.log.record(
                "TRACKING",
                f"{'TRACKED' if tracking else 'LOST'} hands="
                f"{1 if tracking else 0} landmarks={frame['landmark_count']}",
            )

        stable = frame["stable_gesture"]
        if stable != self.last_stable_gesture:
            self.last_stable_gesture = stable
            self.log.record("STABLE_GESTURE", stable)

        middle_press_active = bool(frame.get("middle_press_active", False))
        if middle_press_active != self.last_middle_press_active:
            self.last_middle_press_active = middle_press_active
            self.log.record(
                "MIDDLE_PRESS_STATE",
                "RAISED" if middle_press_active else "LOWERED",
            )

        result = self.state_machine.process_frame(
            stable,
            pointer_norm=frame["pointer_norm"],
            tracking_available=tracking,
        )

        if result["mode"] != self.last_mode.value:
            self.log.record("STATE_TRANSITION", f"{self.last_mode.value} -> {result['mode']}")
            self.last_mode = self.state_machine.mode

        click_sources = []
        if frame.get("middle_click_triggered", False):
            click_sources.append("MIDDLE_FINGER_TAP")
        if frame.get("pinch_triggered", False):
            click_sources.append("CALIBRATED_PINCH")
        if click_sources:
            click_mode = self.state_machine.mode in (
                InteractionMode.DESKTOP_MODE,
                InteractionMode.LAUNCHER_VISIBLE,
                InteractionMode.APP_HOVER,
            )
            click_allowed = (
                tracking
                and click_mode
                and result["cursor_xy"] is not None
            )
            if click_allowed:
                point = result["cursor_xy"]
                move_system_cursor(
                    point,
                    screen_origin=(self.screen_geometry.x(), self.screen_geometry.y()),
                )
                sent = left_click()
                self.log.record(
                    "AIR_MOUSE_CLICK",
                    f"sources={'+'.join(click_sources)}; sent={sent}; "
                    f"x={point[0]}; y={point[1]}; "
                    f"hovered={result['hovered_app']}; "
                    f"pinch_ratio={frame.get('pinch_ratio')}",
                )
            else:
                self.log.record(
                    "AIR_MOUSE_CLICK_BLOCKED",
                    f"sources={'+'.join(click_sources)}; stable={stable}; "
                    f"tracking={tracking}; "
                    f"mode={self.state_machine.mode.value}; "
                    f"cursor={result['cursor_xy']}; "
                    f"pinch_ratio={frame.get('pinch_ratio')}",
                )

        if result["hovered_app"] != self.last_hover:
            self.last_hover = result["hovered_app"]
            self.log.record("APP_HOVER", str(self.last_hover))

        self.launcher.set_air_state(result["hovered_app"], result["dwell_ready"])
        cursor_active = (
            stable in ("POINTING", "PINCH", "PEACE")
            and tracking
            and self.state_machine.mode in (
                InteractionMode.DESKTOP_MODE,
                InteractionMode.LAUNCHER_VISIBLE,
                InteractionMode.APP_HOVER,
            )
            and result["cursor_xy"] is not None
        )
        if cursor_active:
            point = result["cursor_xy"]
            screen_point = (
                point[0] + self.screen_geometry.x(),
                point[1] + self.screen_geometry.y(),
            )
            move_system_cursor(
                point,
                screen_origin=(self.screen_geometry.x(), self.screen_geometry.y()),
            )
            self.air_cursor.set_cursor_position(screen_point)
        else:
            self.air_cursor.hide_cursor()
        if self.state_machine.mode == InteractionMode.APP_LAUNCHING:
            app = self.state_machine.apps[self.state_machine.selected_app]
            self.launcher.set_status(f"Opening {app.label}...")
        elif result["dwell_ready"]:
            label = self.state_machine.apps[result["hovered_app"]].label
            self.launcher.set_status(f"{label} highlighted — lower middle finger to click")
        elif result["hovered_app"] is not None:
            label = self.state_machine.apps[result["hovered_app"]].label
            self.launcher.set_status(f"{label} — raise, then lower middle finger to click")
        elif result["hovered_app"] is None:
            self.launcher.set_status(
                "Point at an app, then raise and lower middle finger to click"
            )

        self._apply_actions(result["actions"], result["selected_app"])

    def _apply_actions(self, actions, selected_app=None):
        for action in actions:
            if action == "SHOW_LAUNCHER":
                self.air_cursor.hide_cursor()
                self.launcher.set_status(
                    "Point at an app, then raise and lower middle finger to click"
                )
                self.launcher.show_animated()
                self.log.record("OVERLAY", "visible; topmost translucent Qt launcher")
            elif action == "HIDE_LAUNCHER":
                self.air_cursor.hide_cursor()
                self.launcher.hide_animated()
                self.log.record("OVERLAY", "hidden")
            elif action == "HIDE_PREVIEW":
                if self.preview.isVisible():
                    self.preview.hide()
                self.log.record("CAMERA_PREVIEW", "hidden; worker/camera continue")
            elif action == "FOCUS_DESKTOP":
                focused = self._focus_desktop_shell()
                self.log.record("DESKTOP_MODE", f"shell_focus_requested={focused}; no Win+D")
            elif action == "LAUNCH_APP" and selected_app is not None:
                self.log.record(
                    "APP_LAUNCH_REQUESTED",
                    f"{selected_app.tile_id} -> {selected_app.command}",
                )
                self.command_worker.launchRequested.emit(selected_app.command)
            elif action == "EXIT_APP":
                self.shutdown()

    @staticmethod
    def _focus_desktop_shell():
        if os.name != "nt":
            return False
        try:
            import ctypes

            user32 = ctypes.windll.user32
            shell_window = user32.GetShellWindow()
            return bool(shell_window and user32.SetForegroundWindow(shell_window))
        except Exception:
            return False

    @Slot(str, bool, str)
    def _on_launch_completed(self, command, succeeded, message):
        self.log.record(
            "APP_LAUNCH_RESULT",
            f"{command}; success={succeeded}; result={message}",
        )
        self.launcher.set_status(message)
        actions = self.state_machine.launch_completed(succeeded)
        if actions:
            self._apply_actions(actions)
        if self.state_machine.mode != self.last_mode:
            self.log.record(
                "STATE_TRANSITION",
                f"{self.last_mode.value} -> {self.state_machine.mode.value}",
            )
            self.last_mode = self.state_machine.mode

    @Slot(str)
    def _on_mouse_selection(self, tile_id):
        result = self.state_machine.select_tile_click(tile_id)
        if result["selected_app"] is not None:
            self.log.record("STABLE_CLICK", tile_id)
            self._apply_actions(result["actions"], result["selected_app"])

    @Slot()
    def shutdown(self):
        if self.is_shutting_down:
            return
        self.is_shutting_down = True
        self.state_machine.close()
        self.log.record("SHUTDOWN", "Exit UI requested")
        self.tray.hide()
        self.air_cursor.close()
        self.launcher.close()
        self.preview.hide()
        camera_stopped = True
        if self.camera_worker.isRunning():
            self.camera_worker.requestInterruption()
            camera_stopped = self.camera_worker.wait(5000)
            if not camera_stopped:
                self.log.record("SHUTDOWN_WAIT", "camera owner still releasing; waiting for safe close")
                self.camera_worker.wait()
        self.command_thread.quit()
        self.command_thread.wait(5000)
        self.log.record(
            "RESOURCES_RELEASED",
            f"camera worker stopped={camera_stopped or not self.camera_worker.isRunning()}; Qt windows closed",
        )
        self.log.close()
        self.app.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AI Vision Control Center")
    app.setQuitOnLastWindowClosed(False)
    screen = app.primaryScreen()
    if screen is None:
        raise RuntimeError("No Windows screen is available for the floating launcher")
    controller = AirTouchController(app, screen.geometry())
    exit_code = app.exec()
    controller.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
