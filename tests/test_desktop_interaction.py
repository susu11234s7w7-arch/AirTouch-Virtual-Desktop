import unittest

from vision_engine.desktop_interaction import (
    DEFAULT_APPS,
    DesktopInteractionStateMachine,
    InteractionMode,
)


class TestDesktopInteractionStateMachine(unittest.TestCase):
    def setUp(self):
        self.machine = DesktopInteractionStateMachine((1920, 1080))

    def _pointer_for(self, tile_id):
        x1, y1, x2, y2 = self.machine.tile_rects[tile_id]
        return (
            ((x1 + x2) / 2) / (self.machine.screen_width - 1),
            ((y1 + y2) / 2) / (self.machine.screen_height - 1),
        )

    def test_open_palm_shows_launcher_and_hides_preview(self):
        result = self.machine.process_frame("OPEN_PALM", now=1.0)
        self.assertEqual(result["mode"], InteractionMode.LAUNCHER_VISIBLE.value)
        self.assertEqual(result["actions"], ["HIDE_PREVIEW", "SHOW_LAUNCHER"])

    def test_fist_enters_desktop_mode_without_minimize_all(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        result = self.machine.process_frame("FIST", now=1.2)
        self.assertEqual(result["mode"], InteractionMode.DESKTOP_MODE.value)
        self.assertEqual(
            result["actions"], ["HIDE_LAUNCHER", "HIDE_PREVIEW", "FOCUS_DESKTOP"]
        )
        self.assertNotIn("MINIMIZE_ALL", result["actions"])
        held = self.machine.process_frame("FIST", now=1.4)
        self.assertEqual(held["actions"], [])

    def test_pointing_tracks_all_arc_apps_with_smoothing_and_dwell(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        self.assertEqual(set(self.machine.tile_rects), {a.tile_id for a in DEFAULT_APPS})
        pointer = self._pointer_for("chrome")
        first = self.machine.process_frame("POINTING", pointer, now=2.0)
        later = self.machine.process_frame("POINTING", pointer, now=2.5)
        self.assertEqual(first["hovered_app"], "chrome")
        self.assertEqual(first["mode"], InteractionMode.APP_HOVER.value)
        self.assertTrue(later["dwell_ready"])
        self.assertEqual(later["actions"], [])

    def test_every_default_app_can_be_hovered(self):
        for app in DEFAULT_APPS:
            with self.subTest(app=app.tile_id):
                machine = DesktopInteractionStateMachine((1920, 1080))
                machine.process_frame("OPEN_PALM", now=1.0)
                x1, y1, x2, y2 = machine.tile_rects[app.tile_id]
                pointer = (
                    ((x1 + x2) / 2) / (machine.screen_width - 1),
                    ((y1 + y2) / 2) / (machine.screen_height - 1),
                )
                result = machine.process_frame("POINTING", pointer, now=2.0)
                self.assertEqual(result["hovered_app"], app.tile_id)
                self.assertEqual(result["mode"], InteractionMode.APP_HOVER.value)
                self.assertEqual(result["actions"], [])

    def test_pinch_selects_only_hovered_app_once(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        self.machine.process_frame("PINCH", pinch_active=True, pinch_triggered=True, now=1.1)
        self.assertEqual(self.machine.mode, InteractionMode.LAUNCHER_VISIBLE)
        self.machine.process_frame("POINTING", self._pointer_for("edge"), now=2.0)
        selected = self.machine.process_frame(
            "PINCH", pinch_active=True, pinch_triggered=True, now=2.1
        )
        self.assertEqual(selected["selected_app"].command, "OPEN_EDGE")
        self.assertEqual(selected["mode"], InteractionMode.APP_LAUNCHING.value)
        again = self.machine.process_frame(
            "PINCH", pinch_active=True, pinch_triggered=True, now=2.2
        )
        self.assertIsNone(again["selected_app"])

    def test_calibrated_pinch_can_select_each_default_app(self):
        for app in DEFAULT_APPS:
            with self.subTest(app=app.tile_id):
                machine = DesktopInteractionStateMachine((1920, 1080))
                machine.process_frame("OPEN_PALM", now=1.0)
                x1, y1, x2, y2 = machine.tile_rects[app.tile_id]
                pointer = (
                    ((x1 + x2) / 2) / (machine.screen_width - 1),
                    ((y1 + y2) / 2) / (machine.screen_height - 1),
                )
                machine.process_frame("POINTING", pointer, now=2.0)
                no_calibrated_click = machine.process_frame(
                    "PINCH", pinch_active=True, pinch_triggered=False, now=2.1
                )
                self.assertIsNone(no_calibrated_click["selected_app"])
                selected = machine.process_frame(
                    "PINCH", pinch_active=True, pinch_triggered=True, now=2.2
                )
                self.assertEqual(selected["selected_app"].command, app.command)

    def test_tracking_loss_and_unknown_cancel_pointer_without_launch(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        self.machine.process_frame("POINTING", self._pointer_for("settings"), now=2.0)
        lost = self.machine.process_frame(
            "POINTING", tracking_available=False, pinch_active=True,
            pinch_triggered=True, now=2.1
        )
        self.assertEqual(lost["cursor_xy"], None)
        self.assertIsNone(lost["selected_app"])
        self.assertEqual(lost["mode"], InteractionMode.LAUNCHER_VISIBLE.value)
        unknown = self.machine.process_frame("UNKNOWN", pinch_triggered=True, now=2.2)
        self.assertIsNone(unknown["selected_app"])
        peace = self.machine.process_frame("PEACE", pinch_triggered=True, now=2.3)
        self.assertIsNone(peace["selected_app"])

    def test_mouse_click_selects_tile_once_and_respects_cooldown(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        click = self.machine.select_tile_click("chrome", now=2.0)
        self.assertEqual(click["selected_app"].command, "OPEN_CHROME")
        self.assertEqual(click["actions"], ["HIDE_LAUNCHER", "LAUNCH_APP"])
        self.assertIsNone(self.machine.select_tile_click("chrome", now=2.1)["selected_app"])
        self.machine.launch_completed(True)
        self.machine.process_frame("OPEN_PALM", now=3.0)
        self.machine.process_frame("POINTING", self._pointer_for("edge"), now=3.1)
        cooldown = self.machine.process_frame(
            "PINCH", pinch_active=True, pinch_triggered=True, now=3.2
        )
        self.assertIsNone(cooldown["selected_app"])

    def test_close_enters_closing_state_and_blocks_future_actions(self):
        self.machine.close()
        result = self.machine.process_frame("OPEN_PALM", now=1.0)
        self.assertEqual(result["mode"], InteractionMode.CLOSING.value)
        self.assertEqual(result["actions"], [])

    def test_launch_completion_keeps_camera_mode_and_failure_restores_launcher(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        self.machine.process_frame("POINTING", self._pointer_for("vscode"), now=2.0)
        self.machine.process_frame("PINCH", pinch_active=True, pinch_triggered=True, now=2.1)
        self.machine.launch_completed(True)
        self.assertEqual(self.machine.mode, InteractionMode.DESKTOP_MODE)

        self.machine.process_frame("OPEN_PALM", now=3.0)
        self.machine.process_frame("POINTING", self._pointer_for("explorer"), now=4.0)
        self.machine.process_frame("PINCH", pinch_active=True, pinch_triggered=True, now=4.1)
        actions = self.machine.launch_completed(False)
        self.assertEqual(actions, ["SHOW_LAUNCHER"])
        self.assertEqual(self.machine.mode, InteractionMode.LAUNCHER_VISIBLE)


if __name__ == "__main__":
    unittest.main()
