from dataclasses import dataclass
import math
import time
import cv2


@dataclass(frozen=True)
class VirtualButton:
    """Represents a touchless virtual button in the on-screen application dock."""

    button_id: str
    label: str
    command: str
    accent: tuple


DEFAULT_DOCK_BUTTONS = (
    VirtualButton("vscode", "VS Code", "OPEN_VSCODE", (255, 160, 40)),
    VirtualButton("explorer", "Explorer", "OPEN_EXPLORER", (60, 200, 255)),
    VirtualButton("calculator", "Calculator", "OPEN_CALCULATOR", (120, 230, 120)),
    VirtualButton("notepad", "Notepad", "OPEN_NOTEPAD", (230, 190, 90)),
    VirtualButton("desktop", "Desktop", "MINIMIZE_ALL", (200, 130, 255)),
    VirtualButton("exit", "Exit UI", "EXIT_APP", (90, 90, 240)),
)


class CursorSmoother:
    """Exponential moving average (EMA) filter with micro-jitter deadzone."""

    def __init__(self, alpha=0.38, deadzone_px=1.5):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0.0, 1.0]")
        self.alpha = float(alpha)
        self.deadzone_px = float(deadzone_px)
        self._sx = None
        self._sy = None

    def reset(self):
        self._sx = None
        self._sy = None

    def update(self, raw_xy):
        """Return smoothed (x, y) tuple or None when tracking is lost."""
        if raw_xy is None:
            self.reset()
            return None

        rx, ry = float(raw_xy[0]), float(raw_xy[1])
        if self._sx is None or self._sy is None:
            self._sx, self._sy = rx, ry
            return (int(round(self._sx)), int(round(self._sy)))

        if math.hypot(rx - self._sx, ry - self._sy) < self.deadzone_px:
            return (int(round(self._sx)), int(round(self._sy)))

        self._sx = self.alpha * rx + (1.0 - self.alpha) * self._sx
        self._sy = self.alpha * ry + (1.0 - self.alpha) * self._sy
        return (int(round(self._sx)), int(round(self._sy)))


def _draw_translucent_rect(frame, pt1, pt2, color, alpha=0.55):
    """Blend a filled rectangle onto the frame for a glassmorphic HUD effect."""
    x1, y1 = max(0, pt1[0]), max(0, pt1[1])
    x2, y2 = min(frame.shape[1], pt2[0]), min(frame.shape[0], pt2[1])
    if x2 <= x1 or y2 <= y1:
        return

    overlay = frame[y1:y2, x1:x2].copy()
    cv2.rectangle(overlay, (0, 0), (x2 - x1, y2 - y1), color, -1)
    cv2.addWeighted(overlay, alpha, frame[y1:y2, x1:x2], 1.0 - alpha, 0, frame[y1:y2, x1:x2])


class VirtualAppDock:
    """Interactive air-touch virtual dock supporting dwell and instant pinch clicks."""

    def __init__(
        self,
        buttons=DEFAULT_DOCK_BUTTONS,
        dwell_seconds=1.0,
        cooldown_seconds=1.8,
    ):
        self.buttons = list(buttons)
        self.dwell_seconds = float(dwell_seconds)
        self.cooldown_seconds = float(cooldown_seconds)

        self.hovered_id = None
        self.hover_started_at = None
        self.progress = 0.0
        self._fired_current_hover = False
        self._pinch_consumed = False
        self.last_triggered_at = -1e9
        self.last_triggered_id = None

        self.toast_message = None
        self.toast_color = (0, 230, 160)
        self.toast_until = 0.0

    def show_toast(self, message, color=(0, 230, 160), duration=2.2, now=None):
        """Display a temporary visual banner confirming a triggered command."""
        now = time.monotonic() if now is None else now
        self.toast_message = str(message)
        self.toast_color = color
        self.toast_until = now + float(duration)

    def compute_button_rects(self, frame_width):
        """Calculate responsive (x1, y1, x2, y2) boxes across the top dock bar."""
        margin_x = 20
        gap = 12
        top_y = 44
        height = 56
        count = max(1, len(self.buttons))
        usable_width = max(320, frame_width - 2 * margin_x - gap * (count - 1))
        btn_width = usable_width // count

        rects = {}
        for idx, btn in enumerate(self.buttons):
            x1 = margin_x + idx * (btn_width + gap)
            x2 = x1 + btn_width
            rects[btn.button_id] = (x1, top_y, x2, top_y + height)
        return rects

    def _hit_test(self, pointer_xy, rects):
        px, py = pointer_xy
        for btn in self.buttons:
            x1, y1, x2, y2 = rects[btn.button_id]
            if x1 <= px <= x2 and y1 <= py <= y2:
                return btn
        return None

    def _reset_hover(self):
        self.hovered_id = None
        self.hover_started_at = None
        self.progress = 0.0
        self._fired_current_hover = False
        self._pinch_consumed = False

    def _empty_result(self, label=None, cooling_down=False):
        return {
            "hovered_id": self.hovered_id,
            "progress": self.progress,
            "triggered": False,
            "trigger_mode": None,
            "command": None,
            "label": label,
            "cooling_down": cooling_down,
        }

    def update(self, pointer_xy, is_pointing, frame_width, is_pinching=False, now=None):
        """Update hover dwell / instant pinch state and return trigger metadata."""
        now = time.monotonic() if now is None else now
        rects = self.compute_button_rects(frame_width)

        if not is_pinching:
            self._pinch_consumed = False

        if pointer_xy is None or (not is_pointing and not is_pinching):
            self._reset_hover()
            return self._empty_result()

        target = self._hit_test(pointer_xy, rects)
        if target is None:
            self._reset_hover()
            return self._empty_result()

        in_cooldown = (now - self.last_triggered_at) < self.cooldown_seconds

        if self.hovered_id != target.button_id:
            self.hovered_id = target.button_id
            self.hover_started_at = now
            self.progress = 0.0
            self._fired_current_hover = False

        if is_pinching and not self._pinch_consumed and not in_cooldown:
            self.progress = 1.0
            self._fired_current_hover = True
            self._pinch_consumed = True
            self.last_triggered_at = now
            self.last_triggered_id = target.button_id
            return {
                "hovered_id": target.button_id,
                "progress": 1.0,
                "triggered": True,
                "trigger_mode": "PINCH",
                "command": target.command,
                "label": target.label,
                "cooling_down": False,
            }

        if in_cooldown or self._fired_current_hover:
            return self._empty_result(label=target.label, cooling_down=in_cooldown)

        if is_pointing:
            elapsed = max(0.0, now - self.hover_started_at)
            self.progress = min(1.0, elapsed / self.dwell_seconds)

            if elapsed >= self.dwell_seconds:
                self._fired_current_hover = True
                self.last_triggered_at = now
                self.last_triggered_id = target.button_id
                return {
                    "hovered_id": target.button_id,
                    "progress": 1.0,
                    "triggered": True,
                    "trigger_mode": "DWELL",
                    "command": target.command,
                    "label": target.label,
                    "cooling_down": False,
                }

        return self._empty_result(label=target.label, cooling_down=False)

    def draw(
        self,
        frame,
        pointer_xy=None,
        is_pointing=False,
        is_pinching=False,
        hud_info=None,
        now=None,
    ):
        """Render the virtual application dock, telemetry HUD, toast, and air cursor."""
        now = time.monotonic() if now is None else now
        height, width = frame.shape[:2]
        rects = self.compute_button_rects(width)

        # 1. Top Virtual Application Dock container
        _draw_translucent_rect(frame, (12, 8), (width - 12, 110), (18, 22, 30), alpha=0.68)
        cv2.putText(
            frame,
            "AIRTOUCH VIRTUAL APP DOCK  |  Point (1.0s) or PINCH to launch instantly",
            (22, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (180, 230, 255),
            1,
            cv2.LINE_AA,
        )

        for btn in self.buttons:
            x1, y1, x2, y2 = rects[btn.button_id]
            is_hovered = self.hovered_id == btn.button_id

            bg_color = (42, 52, 70) if is_hovered else (28, 34, 46)
            _draw_translucent_rect(frame, (x1, y1), (x2, y2), bg_color, alpha=0.78)

            if is_hovered and self.progress > 0.0:
                fill_x2 = x1 + int((x2 - x1) * self.progress)
                _draw_translucent_rect(frame, (x1, y1), (fill_x2, y2), btn.accent, alpha=0.42)

            border_color = btn.accent if is_hovered else (90, 105, 130)
            border_thickness = 2 if is_hovered else 1
            cv2.rectangle(frame, (x1, y1), (x2, y2), border_color, border_thickness)
            cv2.rectangle(frame, (x1, y1), (x1 + 5, y2), btn.accent, -1)

            text_size = cv2.getTextSize(btn.label, cv2.FONT_HERSHEY_SIMPLEX, 0.56, 2)[0]
            text_x = x1 + max(12, ((x2 - x1) - text_size[0]) // 2)
            text_y = y1 + ((y2 - y1) + text_size[1]) // 2
            cv2.putText(
                frame,
                btn.label,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.56,
                (255, 255, 255),
                2 if is_hovered else 1,
                cv2.LINE_AA,
            )

        # 2. Action Toast Banner (centered below dock)
        if self.toast_message and now < self.toast_until:
            toast_size = cv2.getTextSize(
                self.toast_message, cv2.FONT_HERSHEY_SIMPLEX, 0.62, 2
            )[0]
            pill_w = min(width - 40, toast_size[0] + 48)
            tx1 = (width - pill_w) // 2
            tx2 = tx1 + pill_w
            _draw_translucent_rect(frame, (tx1, 120), (tx2, 160), (20, 28, 40), alpha=0.82)
            cv2.rectangle(frame, (tx1, 120), (tx2, 160), self.toast_color, 2)
            cv2.putText(
                frame,
                self.toast_message,
                (tx1 + 22, 147),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

        # 3. Left Telemetry HUD Panel
        if hud_info:
            panel_w = min(375, width - 24)
            _draw_translucent_rect(frame, (12, 122), (12 + panel_w, 396), (18, 22, 30), alpha=0.65)
            cv2.rectangle(frame, (12, 122), (12 + panel_w, 396), (70, 95, 125), 1)

            rows = [
                ("AIRTOUCH VIRTUAL DESKTOP", (100, 255, 180), 0.62, 2),
                (f"Hands: {hud_info.get('hands_count', 0)}   FPS: {hud_info.get('fps', 0.0):.1f}", (210, 235, 255), 0.56, 1),
                (f"Gesture: {hud_info.get('display_gesture', 'NO HAND')}", (0, 255, 255), 0.68, 2),
                (f"Raw: {hud_info.get('raw_gesture', 'UNKNOWN')}   Stability: {hud_info.get('stability_text', '0/0')}", (200, 215, 230), 0.50, 1),
                (f"Confidence: {hud_info.get('confidence', 0.0):.2f}", (200, 215, 230), 0.52, 1),
                (f"Controller: {hud_info.get('controller_message', '')[:36]}", (120, 210, 255), 0.50, 1),
                (f"Action: {hud_info.get('last_command_message', '')[:38]}", (120, 255, 140), 0.50, 1),
            ]

            y_cursor = 152
            for text, color, scale, thickness in rows:
                cv2.putText(
                    frame,
                    text,
                    (24, y_cursor),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    scale,
                    color,
                    thickness,
                    cv2.LINE_AA,
                )
                y_cursor += 37

        # 4. Bottom Gesture Guide Bar
        guide_y1 = max(120, height - 42)
        _draw_translucent_rect(frame, (12, guide_y1), (width - 12, height - 10), (18, 22, 30), alpha=0.68)
        cv2.putText(
            frame,
            "OPEN_PALM -> FIST: Minimize Desktop  |  PEACE: VS Code  |  POINTING / PINCH: Virtual Dock  |  THUMBS_UP: Confirm  |  Q/ESC: Exit",
            (20, height - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (215, 225, 240),
            1,
            cv2.LINE_AA,
        )

        # 5. Virtual Air Cursor at smoothed index fingertip
        if pointer_xy is not None:
            px, py = int(pointer_xy[0]), int(pointer_xy[1])
            if is_pinching:
                cv2.circle(frame, (px, py), 13, (0, 255, 120), 3, cv2.LINE_AA)
                cv2.circle(frame, (px, py), 6, (255, 255, 255), -1, cv2.LINE_AA)
            elif is_pointing:
                cv2.circle(frame, (px, py), 10, (0, 255, 255), 2, cv2.LINE_AA)
                cv2.circle(frame, (px, py), 4, (0, 255, 180), -1, cv2.LINE_AA)
                if self.progress > 0.0:
                    end_angle = int(360 * self.progress)
                    cv2.ellipse(
                        frame,
                        (px, py),
                        (18, 18),
                        -90,
                        0,
                        end_angle,
                        (0, 255, 120),
                        3,
                        cv2.LINE_AA,
                    )
            else:
                cv2.circle(frame, (px, py), 5, (180, 200, 220), -1, cv2.LINE_AA)
