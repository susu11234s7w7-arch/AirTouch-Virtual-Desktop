"""Pure state and pointer logic for AirTouch's desktop floating launcher."""

from dataclasses import dataclass
from enum import Enum
import math
import time

from vision_engine.virtual_interface import CursorSmoother


class InteractionMode(str, Enum):
    MONITORING = "MONITORING"
    DESKTOP_MODE = "DESKTOP_MODE"
    LAUNCHER_VISIBLE = "LAUNCHER_VISIBLE"
    APP_HOVER = "APP_HOVER"
    APP_LAUNCHING = "APP_LAUNCHING"
    CLOSING = "CLOSING"


@dataclass(frozen=True)
class LauncherApp:
    tile_id: str
    label: str
    command: str
    fallback_glyph: str
    accent: tuple


DEFAULT_APPS = (
    LauncherApp("chrome", "Google Chrome", "OPEN_CHROME", "C", (66, 133, 244)),
    LauncherApp("vscode", "Visual Studio Code", "OPEN_VSCODE", "<> ", (0, 122, 204)),
    LauncherApp("explorer", "File Explorer", "OPEN_EXPLORER", "▰", (255, 190, 75)),
    LauncherApp("edge", "Microsoft Edge", "OPEN_EDGE", "e", (0, 170, 190)),
    LauncherApp("settings", "Windows Settings", "OPEN_SETTINGS", "⚙", (150, 165, 190)),
)


def compute_arc_tile_rects(screen_width, screen_height, tile_width=132, tile_height=150):
    """Place five app hit regions on an upper semicircle around screen center."""
    width = max(1, int(screen_width))
    height = max(1, int(screen_height))
    radius = min(270.0, width * 0.27, height * 0.27)
    center_x = width / 2.0
    center_y = height / 2.0 + min(45.0, height * 0.04)
    angles = (-70.0, -35.0, 0.0, 35.0, 70.0)
    rects = {}
    for app, angle in zip(DEFAULT_APPS, angles):
        theta = angle * 3.141592653589793 / 180.0
        x = center_x + radius * math.sin(theta)
        y = center_y - radius * math.cos(theta)
        rects[app.tile_id] = (
            int(round(x - tile_width / 2)),
            int(round(y - tile_height / 2)),
            int(round(x + tile_width / 2)),
            int(round(y + tile_height / 2)),
        )
    return rects


def map_normalized_to_screen(x, y, screen_width, screen_height, mirrored=True):
    """Map a normalized index-tip point to physical desktop pixels."""
    if x is None or y is None:
        return None
    nx = max(0.0, min(1.0, float(x)))
    ny = max(0.0, min(1.0, float(y)))
    if not mirrored:
        nx = 1.0 - nx
    return (
        int(round(nx * max(0, int(screen_width) - 1))),
        int(round(ny * max(0, int(screen_height) - 1))),
    )


class DesktopInteractionStateMachine:
    """Coordinate gestures, pointer hover feedback, and click-to-launch."""

    def __init__(
        self,
        screen_size,
        cooldown_seconds=1.8,
        dwell_seconds=0.5,
        cursor_smoother=None,
        apps=DEFAULT_APPS,
    ):
        self.screen_width, self.screen_height = map(int, screen_size)
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.dwell_seconds = max(0.0, float(dwell_seconds))
        self.apps = {app.tile_id: app for app in apps}
        self.tile_rects = compute_arc_tile_rects(self.screen_width, self.screen_height)
        self.cursor_smoother = cursor_smoother or CursorSmoother(
            alpha=0.82, deadzone_px=0.8
        )
        self.mode = InteractionMode.MONITORING
        self.cursor_xy = None
        self.hovered_app = None
        self.hover_started_at = None
        self.dwell_ready = False
        self.last_launch_at = -1e9
        self.selected_app = None

    @property
    def launcher_visible(self):
        return self.mode in (
            InteractionMode.LAUNCHER_VISIBLE,
            InteractionMode.APP_HOVER,
        )

    def _clear_pointer(self):
        self.cursor_xy = None
        self.hovered_app = None
        self.hover_started_at = None
        self.dwell_ready = False
        self.cursor_smoother.reset()

    def hit_test(self, point):
        if point is None:
            return None
        px, py = point
        for tile_id, (x1, y1, x2, y2) in self.tile_rects.items():
            if x1 <= px <= x2 and y1 <= py <= y2:
                return tile_id
        return None

    def _update_pointer(self, pointer_norm, now, track_hover=True):
        if pointer_norm is None:
            self._clear_pointer()
            if self.mode == InteractionMode.APP_HOVER:
                self.mode = InteractionMode.LAUNCHER_VISIBLE
            return [], None
        raw = map_normalized_to_screen(
            pointer_norm[0], pointer_norm[1], self.screen_width, self.screen_height
        )
        self.cursor_xy = self.cursor_smoother.update(raw)
        if not track_hover:
            self.hovered_app = None
            self.hover_started_at = None
            self.dwell_ready = False
            return [], None

        target = self.hit_test(self.cursor_xy)
        if target != self.hovered_app:
            self.hovered_app = target
            self.hover_started_at = now if target else None
            self.dwell_ready = target is not None and self.dwell_seconds <= 0.0
        elif target is not None and self.hover_started_at is not None:
            self.dwell_ready = now - self.hover_started_at >= self.dwell_seconds
        self.mode = (
            InteractionMode.APP_HOVER
            if self.hovered_app is not None
            else InteractionMode.LAUNCHER_VISIBLE
        )

        # Hover only highlights a tile. Application launch is reserved for a
        # deliberate physical mouse click or calibrated one-shot air click.
        return [], None

    def process_frame(
        self,
        gesture,
        pointer_norm=None,
        tracking_available=True,
        now=None,
    ):
        """Process one stabilized camera result and return UI/action requests."""
        now = time.monotonic() if now is None else float(now)
        gesture = gesture.strip().upper() if isinstance(gesture, str) else "UNKNOWN"
        actions = []
        selected = None

        if self.mode == InteractionMode.CLOSING:
            return self._result(actions, selected)

        if not tracking_available:
            self._clear_pointer()
            if self.mode == InteractionMode.APP_HOVER:
                self.mode = InteractionMode.LAUNCHER_VISIBLE
            return self._result(actions, selected)

        if gesture == "BACK_OF_HAND":
            self.close()
            return self._result(["EXIT_APP"], selected)

        if self.mode == InteractionMode.APP_LAUNCHING:
            return self._result(actions, selected)

        if gesture == "FIST":
            if self.mode != InteractionMode.DESKTOP_MODE:
                actions.extend(("HIDE_LAUNCHER", "HIDE_PREVIEW", "FOCUS_DESKTOP"))
                self.mode = InteractionMode.DESKTOP_MODE
            self._clear_pointer()
            return self._result(actions, selected)

        if gesture == "OPEN_PALM":
            if not self.launcher_visible:
                actions.extend(("HIDE_PREVIEW", "SHOW_LAUNCHER"))
                # OPEN_PALM begins a fresh, intentional launcher session; the
                # previous app's cooldown must not delay the next selection.
                self.last_launch_at = -1e9
            self.mode = InteractionMode.LAUNCHER_VISIBLE
            self._clear_pointer()
            return self._result(actions, selected)

        if gesture == "POINTING":
            if self.launcher_visible or self.mode == InteractionMode.DESKTOP_MODE:
                actions, selected = self._update_pointer(
                    pointer_norm,
                    now,
                    track_hover=self.launcher_visible,
                )
            return self._result(actions, selected)

        if gesture == "PINCH":
            # The camera worker emits a separate calibrated one-shot click.
            # Keep the last pointed coordinate so that click lands there.
            return self._result(actions, selected)

        # PEACE, UNKNOWN, and all unassigned gestures are safe no-ops.
        self._clear_pointer()
        if self.mode == InteractionMode.APP_HOVER:
            self.mode = InteractionMode.LAUNCHER_VISIBLE
        return self._result(actions, selected)

    def select_tile_click(self, tile_id, now=None):
        """Handle a real mouse click inside a tile's shaped input region."""
        now = time.monotonic() if now is None else float(now)
        if not self.launcher_visible or tile_id not in self.apps:
            return self._result([], None)
        actions, selected = self._begin_launch(tile_id, now)
        return self._result(actions, selected)

    def _begin_launch(self, tile_id, now):
        if now - self.last_launch_at < self.cooldown_seconds:
            return [], None
        app = self.apps[tile_id]
        self.selected_app = app.tile_id
        self.last_launch_at = now
        self.mode = InteractionMode.APP_LAUNCHING
        self._clear_pointer()
        return ["HIDE_LAUNCHER", "LAUNCH_APP"], app

    def launch_completed(self, succeeded):
        """Keep camera monitoring after launch; reopen the dock only on failure."""
        if self.mode != InteractionMode.APP_LAUNCHING:
            return []
        if succeeded:
            self.mode = InteractionMode.DESKTOP_MODE
            self._clear_pointer()
            return []
        self.mode = InteractionMode.LAUNCHER_VISIBLE
        self.selected_app = None
        return ["SHOW_LAUNCHER"]

    def close(self):
        self.mode = InteractionMode.CLOSING
        self._clear_pointer()

    def _result(self, actions, selected):
        return {
            "mode": self.mode.value,
            "actions": actions,
            "cursor_xy": self.cursor_xy,
            "hovered_app": self.hovered_app,
            "dwell_ready": self.dwell_ready,
            "selected_app": selected,
        }
