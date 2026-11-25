import unittest
from unittest.mock import MagicMock
import numpy as np

from main import execute_windows_command, GESTURE_STABILIZATION
from vision_engine.gesture_classifier import GestureClassifier
from vision_engine.gesture_command_controller import GestureCommandController
from vision_engine.virtual_interface import VirtualAppDock


def _make_landmarks(
    index_up=False,
    middle_up=False,
    ring_up=False,
    pinky_up=False,
    thumb_out=False,
):
    """Build 21 normalized hand landmarks with controllable finger states."""
    pts = [{"x": 0.5, "y": 0.8} for _ in range(21)]

    # Thumb landmarks (2, 3, 4) and pinky MCP (17)
    pts[17] = {"x": 0.70, "y": 0.70}
    pts[2] = {"x": 0.36, "y": 0.70}
    pts[3] = {"x": 0.30, "y": 0.64}
    if thumb_out:
        pts[4] = {"x": 0.22, "y": 0.56}
    else:
        pts[4] = {"x": 0.55, "y": 0.72}

    finger_bases = {
        "index": (5, 6, 7, 0.42, index_up),
        "middle": (9, 10, 11, 0.50, middle_up),
        "ring": (13, 14, 15, 0.58, ring_up),
        "pinky": (17, 18, 19, 0.70, pinky_up),
    }

    for _, (mcp, pip, dip, x_pos, is_up) in finger_bases.items():
        pts[mcp] = {"x": x_pos, "y": 0.70}
        pts[pip] = {"x": x_pos, "y": 0.52}
        pts[dip] = {"x": x_pos, "y": 0.34 if is_up else 0.66}

    return pts


class TestAirTouchVirtualDesktop(unittest.TestCase):
    def test_classifier_detects_valid_gestures_and_ignores_unassigned(self):
        classifier = GestureClassifier()

        # Unassigned single-finger pose must fall back to UNKNOWN
        unassigned_pose = _make_landmarks(middle_up=True)
        res_unassigned = classifier.classify(unassigned_pose)
        self.assertEqual(res_unassigned["gesture"], "UNKNOWN")

        self.assertEqual(
            classifier.classify(
                _make_landmarks(
                    index_up=True,
                    middle_up=True,
                    ring_up=True,
                    pinky_up=True,
                    thumb_out=True,
                )
            )["gesture"],
            "OPEN_PALM",
        )
        self.assertEqual(classifier.classify(_make_landmarks())["gesture"], "FIST")
        self.assertEqual(
            classifier.classify(_make_landmarks(index_up=True, middle_up=True))["gesture"],
            "PEACE",
        )
        self.assertEqual(
            classifier.classify(_make_landmarks(index_up=True))["gesture"],
            "POINTING",
        )
        self.assertEqual(
            classifier.classify(_make_landmarks(thumb_out=True))["gesture"],
            "THUMBS_UP",
        )

    def test_controller_safe_gestures_and_unassigned_pose(self):
        controller = GestureCommandController()

        # Unassigned gesture string should not execute any command
        res = controller.process("UNASSIGNED_GESTURE", now=1.0)
        self.assertFalse(res["executed"])
        self.assertIsNone(res["command"])

        # POINTING and THUMBS_UP stay armed and do not execute OS commands
        pointing_res = controller.process("POINTING", now=2.0)
        self.assertFalse(pointing_res["executed"])
        self.assertTrue(controller.armed)

        thumbs_res = controller.process("THUMBS_UP", now=3.0)
        self.assertFalse(thumbs_res["executed"])
        self.assertTrue(controller.armed)

        self.assertIn("POINTING", GESTURE_STABILIZATION)
        self.assertIn("THUMBS_UP", GESTURE_STABILIZATION)

    def test_virtual_app_dock_dwell_and_cooldown(self):
        dock = VirtualAppDock(dwell_seconds=1.0, cooldown_seconds=2.0)
        rects = dock.compute_button_rects(1280)
        x1, y1, x2, y2 = rects["vscode"]
        center = ((x1 + x2) // 2, (y1 + y2) // 2)

        r0 = dock.update(center, is_pointing=True, frame_width=1280, now=10.0)
        self.assertEqual(r0["hovered_id"], "vscode")
        self.assertFalse(r0["triggered"])

        r1 = dock.update(center, is_pointing=True, frame_width=1280, now=10.5)
        self.assertAlmostEqual(r1["progress"], 0.5, places=2)
        self.assertFalse(r1["triggered"])

        r2 = dock.update(center, is_pointing=True, frame_width=1280, now=11.0)
        self.assertTrue(r2["triggered"])
        self.assertEqual(r2["command"], "OPEN_VSCODE")

        # Cooldown suppresses immediate re-trigger while hovering
        r3 = dock.update(center, is_pointing=True, frame_width=1280, now=11.5)
        self.assertFalse(r3["triggered"])

        # Moving cursor away resets hover
        r4 = dock.update((10, 600), is_pointing=True, frame_width=1280, now=12.0)
        self.assertIsNone(r4["hovered_id"])
        self.assertEqual(r4["progress"], 0.0)

    def test_virtual_app_dock_renders_without_error(self):
        dock = VirtualAppDock()
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        dock.update((100, 70), is_pointing=True, frame_width=1280, now=1.0)
        dock.update((100, 70), is_pointing=True, frame_width=1280, now=1.5)
        dock.draw(
            frame,
            pointer_xy=(100, 70),
            is_pointing=True,
            hud_info={
                "hands_count": 1,
                "fps": 30.0,
                "display_gesture": "POINTING",
                "raw_gesture": "POINTING",
                "stability_text": "2/2",
                "confidence": 1.0,
                "controller_message": "Virtual pointer active",
                "last_command_message": "No command executed",
            },
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
