import unittest
from unittest.mock import MagicMock
import numpy as np

from main import execute_windows_command, GESTURE_STABILIZATION
from vision_engine.gesture_classifier import GestureClassifier
from vision_engine.gesture_command_controller import GestureCommandController
from vision_engine.virtual_interface import CursorSmoother, VirtualAppDock


def _make_landmarks(
    index_up=False,
    middle_up=False,
    ring_up=False,
    pinky_up=False,
    thumb_out=False,
    pinching=False,
    scale=1.0,
):
    """Build 21 realistic normalized hand landmarks with optional scale factor."""
    pts = [{"x": 0.5, "y": 0.8} for _ in range(21)]

    # Wrist (0) and Palm base
    pts[0] = {"x": 0.50, "y": 0.82}
    pts[17] = {"x": 0.70, "y": 0.70}
    pts[2] = {"x": 0.36, "y": 0.70}
    pts[3] = {"x": 0.30, "y": 0.64}

    if thumb_out:
        pts[4] = {"x": 0.22, "y": 0.56}
    else:
        pts[4] = {"x": 0.55, "y": 0.72}

    finger_specs = {
        "index": (5, 6, 7, 8, 0.42, index_up),
        "middle": (9, 10, 11, 12, 0.50, middle_up),
        "ring": (13, 14, 15, 16, 0.58, ring_up),
        "pinky": (17, 18, 19, 20, 0.70, pinky_up),
    }

    for _, (mcp, pip, dip, tip, x_pos, is_up) in finger_specs.items():
        pts[mcp] = {"x": x_pos, "y": 0.70}
        pts[pip] = {"x": x_pos, "y": 0.52}
        pts[dip] = {"x": x_pos, "y": 0.36 if is_up else 0.66}
        pts[tip] = {"x": x_pos, "y": 0.24 if is_up else 0.74}

    if pinching:
        # Bring thumb tip and index tip within pinch ratio while reaching out
        pts[4] = {"x": 0.43, "y": 0.40}
        pts[8] = {"x": 0.42, "y": 0.39}

    if scale != 1.0:
        cx, cy = 0.5, 0.5
        pts = [
            {"x": cx + (p["x"] - cx) * scale, "y": cy + (p["y"] - cy) * scale}
            for p in pts
        ]

    return pts


class TestAirTouchVirtualDesktop(unittest.TestCase):
    def test_classifier_detects_valid_gestures_and_confidence(self):
        classifier = GestureClassifier()

        unassigned_pose = _make_landmarks(middle_up=True)
        res_unassigned = classifier.classify(unassigned_pose)
        self.assertEqual(res_unassigned["gesture"], "UNKNOWN")
        self.assertEqual(res_unassigned["confidence"], 0.0)

        cases = [
            (
                _make_landmarks(
                    index_up=True,
                    middle_up=True,
                    ring_up=True,
                    pinky_up=True,
                    thumb_out=True,
                ),
                "OPEN_PALM",
            ),
            (_make_landmarks(), "FIST"),
            (_make_landmarks(index_up=True, middle_up=True), "PEACE"),
            (_make_landmarks(index_up=True), "POINTING"),
            (_make_landmarks(thumb_out=True), "THUMBS_UP"),
            (
                _make_landmarks(
                    middle_up=True, ring_up=True, pinky_up=True, pinching=True
                ),
                "PINCH",
            ),
        ]

        for landmarks, expected_gesture in cases:
            result = classifier.classify(landmarks)
            self.assertEqual(result["gesture"], expected_gesture)
            self.assertGreaterEqual(result["confidence"], 0.62)
            self.assertLessEqual(result["confidence"], 0.99)

    def test_classifier_is_scale_invariant(self):
        classifier = GestureClassifier()
        for scale in (0.45, 1.0, 1.75):
            self.assertEqual(
                classifier.classify(_make_landmarks(index_up=True, scale=scale))["gesture"],
                "POINTING",
            )
            self.assertEqual(
                classifier.classify(
                    _make_landmarks(middle_up=True, ring_up=True, pinching=True, scale=scale)
                )["gesture"],
                "PINCH",
            )
            self.assertEqual(
                classifier.classify(_make_landmarks(scale=scale))["gesture"],
                "FIST",
            )

    def test_controller_safe_gestures_and_pinch(self):
        controller = GestureCommandController()

        res = controller.process("UNASSIGNED_GESTURE", now=1.0)
        self.assertFalse(res["executed"])
        self.assertIsNone(res["command"])

        for gesture in ("POINTING", "PINCH", "THUMBS_UP"):
            step_res = controller.process(gesture, now=2.0)
            self.assertFalse(step_res["executed"])
            self.assertTrue(controller.armed)
            self.assertIn(gesture, GESTURE_STABILIZATION)

    def test_cursor_smoother_ema_deadzone_and_reset(self):
        smoother = CursorSmoother(alpha=0.5, deadzone_px=2.0)

        self.assertEqual(smoother.update((100, 100)), (100, 100))
        # Micro-jitter within deadzone is suppressed
        self.assertEqual(smoother.update((101, 101)), (100, 100))
        # Large movement is smoothed smoothly toward target
        smoothed = smoother.update((200, 100))
        self.assertEqual(smoothed, (150, 100))
        # Reset on None avoids jump on re-entry
        self.assertIsNone(smoother.update(None))
        self.assertEqual(smoother.update((400, 300)), (400, 300))

    def test_virtual_app_dock_dwell_and_instant_pinch(self):
        dock = VirtualAppDock(dwell_seconds=1.0, cooldown_seconds=2.0)
        rects = dock.compute_button_rects(1280)
        x1, y1, x2, y2 = rects["vscode"]
        center = ((x1 + x2) // 2, (y1 + y2) // 2)

        # Dwell flow
        r0 = dock.update(center, is_pointing=True, frame_width=1280, now=10.0)
        self.assertEqual(r0["hovered_id"], "vscode")
        self.assertFalse(r0["triggered"])

        r1 = dock.update(center, is_pointing=True, frame_width=1280, now=10.5)
        self.assertAlmostEqual(r1["progress"], 0.5, places=2)

        r2 = dock.update(center, is_pointing=True, frame_width=1280, now=11.0)
        self.assertTrue(r2["triggered"])
        self.assertEqual(r2["trigger_mode"], "DWELL")
        self.assertEqual(r2["command"], "OPEN_VSCODE")

        # Cooldown blocks immediate repeat
        r3 = dock.update(center, is_pointing=True, frame_width=1280, now=11.5)
        self.assertFalse(r3["triggered"])

        # Instant PINCH flow after cooldown expires
        ex1, ey1, ex2, ey2 = rects["explorer"]
        exp_center = ((ex1 + ex2) // 2, (ey1 + ey2) // 2)
        p1 = dock.update(
            exp_center,
            is_pointing=False,
            frame_width=1280,
            is_pinching=True,
            now=15.0,
        )
        self.assertTrue(p1["triggered"])
        self.assertEqual(p1["trigger_mode"], "PINCH")
        self.assertEqual(p1["command"], "OPEN_EXPLORER")

        # Holding pinch continuously does not re-fire even after cooldown
        p2 = dock.update(
            exp_center,
            is_pointing=False,
            frame_width=1280,
            is_pinching=True,
            now=18.0,
        )
        self.assertFalse(p2["triggered"])

    def test_virtual_app_dock_renders_toast_and_cursor(self):
        dock = VirtualAppDock()
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        dock.show_toast("[PINCH] VS Code launched", now=1.0)
        dock.update((100, 70), is_pointing=False, frame_width=1280, is_pinching=True, now=1.2)
        dock.draw(
            frame,
            pointer_xy=(100, 70),
            is_pointing=False,
            is_pinching=True,
            hud_info={
                "hands_count": 1,
                "fps": 30.0,
                "display_gesture": "PINCH",
                "raw_gesture": "PINCH",
                "stability_text": "2/2",
                "confidence": 0.91,
                "controller_message": "Pinch click active",
                "last_command_message": "OPEN_VSCODE executed",
            },
            now=1.5,
        )
        self.assertGreater(int(frame.sum()), 0)

    def test_execute_windows_command_whitelist(self):
        mock_exec = MagicMock()
        mock_exec.minimize_all.return_value = "MINIMIZE_ALL executed"
        mock_exec.open_vscode.return_value = "OPEN_VSCODE executed"
        mock_exec.open_explorer.return_value = "OPEN_EXPLORER executed"
        mock_exec.open_calculator.return_value = "OPEN_CALCULATOR executed"
        mock_exec.open_notepad.return_value = "OPEN_NOTEPAD executed"

        self.assertEqual(
            execute_windows_command(mock_exec, "OPEN_EXPLORER"),
            "OPEN_EXPLORER executed",
        )
        self.assertEqual(
            execute_windows_command(mock_exec, "OPEN_CALCULATOR"),
            "OPEN_CALCULATOR executed",
        )
        self.assertEqual(
            execute_windows_command(mock_exec, "OPEN_NOTEPAD"),
            "OPEN_NOTEPAD executed",
        )
        with self.assertRaises(ValueError):
            execute_windows_command(mock_exec, "UNAUTHORIZED_COMMAND")


if __name__ == "__main__":
    unittest.main()
