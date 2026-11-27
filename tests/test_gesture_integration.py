import unittest

from vision_engine.gesture_command_controller import GestureCommandController


class TestGestureIntegration(unittest.TestCase):
    def test_overlay_gesture_mapping_and_no_direct_gesture_launch(self):
        controller = GestureCommandController()

        show = controller.process("OPEN_PALM", now=1.0)
        self.assertEqual(show["command"], "SHOW_OVERLAY")
        self.assertTrue(show["executed"])

        hide = controller.process("FIST", now=1.1)
        self.assertEqual(hide["command"], "HIDE_OVERLAY")
        self.assertTrue(hide["executed"])
        self.assertNotIn("MINIMIZE_ALL", hide.values())

        for gesture in ("PEACE", "PINCH", "THUMBS_UP"):
            action = controller.process(gesture, now=1.5)
            self.assertIsNone(action["command"])
            self.assertFalse(action["executed"])


if __name__ == "__main__":
    unittest.main()
