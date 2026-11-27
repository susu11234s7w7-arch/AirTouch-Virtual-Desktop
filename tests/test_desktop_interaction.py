import unittest

from vision_engine.desktop_interaction import (
    DEFAULT_APPS,
    DesktopInteractionStateMachine,
    InteractionMode,
)
from vision_engine.virtual_interface import CursorSmoother


class TestDesktopInteractionStateMachine(unittest.TestCase):
    def setUp(self):
        self.machine = DesktopInteractionStateMachine(
            (1920, 1080),
            cursor_smoother=CursorSmoother(alpha=1.0, deadzone_px=0.0),
        )

    def _pointer_for(self, machine, tile_id):
        x1, y1, x2, y2 = machine.tile_rects[tile_id]
        return (
            ((x1 + x2) / 2) / (machine.screen_width - 1),
            ((y1 + y2) / 2) / (machine.screen_height - 1),
        )

    def _point(self, machine, tile_id, now):
        return machine.process_frame(
            "POINTING", self._pointer_for(machine, tile_id), now=now
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

    def test_pointing_moves_system_cursor_in_desktop_mode_after_launch(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        self.machine.select_tile_click("vscode", now=2.0)
        self.machine.launch_completed(True)

        point = self.machine.process_frame("POINTING", (0.25, 0.50), now=2.2)

        self.assertEqual(point["mode"], InteractionMode.DESKTOP_MODE.value)
        self.assertIsNotNone(point["cursor_xy"])
        self.assertIsNone(point["selected_app"])
        self.assertEqual(point["actions"], [])

    def test_back_of_hand_requests_clean_shutdown_once(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        result = self.machine.process_frame("BACK_OF_HAND", now=2.0)
        self.assertEqual(result["mode"], InteractionMode.CLOSING.value)
        self.assertEqual(result["actions"], ["EXIT_APP"])
        held = self.machine.process_frame("BACK_OF_HAND", now=2.4)
        self.assertEqual(held["actions"], [])

    def test_pointing_moves_cursor_and_hover_only_highlights(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        self.assertEqual(set(self.machine.tile_rects), {a.tile_id for a in DEFAULT_APPS})

        selected = self._point(self.machine, "chrome", 2.0)

        self.assertEqual(selected["hovered_app"], "chrome")
        self.assertEqual(selected["cursor_xy"], tuple(
            round(value * (size - 1))
            for value, size in zip(self._pointer_for(self.machine, "chrome"), (1920, 1080))
        ))
        self.assertIsNone(selected["selected_app"])
        self.assertEqual(selected["mode"], InteractionMode.APP_HOVER.value)
        self.assertEqual(selected["actions"], [])

        held = self._point(self.machine, "chrome", 2.6)
        self.assertIsNone(held["selected_app"])
        self.assertEqual(held["actions"], [])

    def test_every_default_app_can_be_hovered_without_launching(self):
        for app in DEFAULT_APPS:
            with self.subTest(app=app.tile_id):
                machine = DesktopInteractionStateMachine(
                    (1920, 1080),
                    cursor_smoother=CursorSmoother(alpha=1.0, deadzone_px=0.0),
                )
                machine.process_frame("OPEN_PALM", now=1.0)
                result = self._point(machine, app.tile_id, 2.0)
                self.assertEqual(result["hovered_app"], app.tile_id)
                self.assertIsNone(result["selected_app"])
                self.assertEqual(result["actions"], [])

    def test_leaving_and_reentering_tile_allows_explicit_click(self):
        self.machine.process_frame("OPEN_PALM", now=0.5)
        first = self._point(self.machine, "edge", 1.0)
        self.assertEqual(first["hovered_app"], "edge")
        self.assertIsNone(first["selected_app"])

        self.machine.process_frame("POINTING", (0.0, 0.0), now=1.5)
        self.assertIsNone(self.machine.hovered_app)
        reentered = self._point(self.machine, "edge", 3.0)
        self.assertEqual(reentered["hovered_app"], "edge")
        self.assertIsNone(reentered["selected_app"])
        selected = self.machine.select_tile_click("edge", now=3.1)
        self.assertEqual(selected["selected_app"].command, "OPEN_EDGE")

    def test_failed_launch_does_not_repeat_without_another_click(self):
        self.machine.process_frame("OPEN_PALM", now=0.5)
        self._point(self.machine, "explorer", 1.0)
        first = self.machine.select_tile_click("explorer", now=1.0)
        self.assertEqual(first["selected_app"].command, "OPEN_EXPLORER")
        self.assertEqual(self.machine.launch_completed(False), ["SHOW_LAUNCHER"])

        held = self._point(self.machine, "explorer", 1.6)
        self.assertIsNone(held["selected_app"])
        self.assertEqual(held["actions"], [])

        waiting = self.machine.select_tile_click("explorer", now=2.0)
        self.assertIsNone(waiting["selected_app"])
        second = self.machine.select_tile_click("explorer", now=3.0)
        self.assertEqual(second["selected_app"].command, "OPEN_EXPLORER")

    def test_pinch_never_selects_or_launches_an_app(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        pointing = self._point(self.machine, "chrome", 2.4)
        cursor_before_press = pointing["cursor_xy"]
        pinch = self.machine.process_frame("PINCH", now=2.5)
        self.assertIsNone(pinch["selected_app"])
        self.assertEqual(pinch["actions"], [])
        self.assertEqual(pinch["mode"], InteractionMode.APP_HOVER.value)
        self.assertEqual(pinch["cursor_xy"], cursor_before_press)

        pinch_again = self.machine.process_frame("PINCH", now=3.6)
        self.assertIsNone(pinch_again["selected_app"])
        self.assertEqual(pinch_again["actions"], [])
        pointed = self._point(self.machine, "edge", 3.7)
        self.assertEqual(pointed["hovered_app"], "edge")
        self.assertIsNone(pointed["selected_app"])

    def test_peace_never_launches_an_app(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        peace = self.machine.process_frame(
            "PEACE", self._pointer_for(self.machine, "vscode"), now=2.0
        )
        self.assertIsNone(peace["selected_app"])
        self.assertEqual(peace["actions"], [])
        self.assertEqual(peace["mode"], InteractionMode.LAUNCHER_VISIBLE.value)

    def test_unknown_and_tracking_loss_cancel_hover_without_launch(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        unknown = self.machine.process_frame(
            "UNKNOWN", self._pointer_for(self.machine, "settings"), now=2.0
        )
        self.assertIsNone(unknown["selected_app"])
        lost = self.machine.process_frame(
            "POINTING", self._pointer_for(self.machine, "settings"),
            tracking_available=False, now=2.1
        )
        self.assertIsNone(lost["cursor_xy"])
        self.assertIsNone(lost["selected_app"])
        self.assertEqual(lost["mode"], InteractionMode.LAUNCHER_VISIBLE.value)

        selected = self._point(self.machine, "settings", 4.0)
        self.assertEqual(selected["hovered_app"], "settings")
        self.assertIsNone(selected["selected_app"])

    def test_mouse_click_fallback_and_hover_cooldown(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        click = self.machine.select_tile_click("chrome", now=2.0)
        self.assertEqual(click["selected_app"].command, "OPEN_CHROME")
        self.assertEqual(click["actions"], ["HIDE_LAUNCHER", "LAUNCH_APP"])
        self.assertIsNone(self.machine.select_tile_click("chrome", now=2.1)["selected_app"])
        self.machine.launch_completed(False)

        self.machine.process_frame("OPEN_PALM", now=2.2)
        waiting_for_cooldown = self._point(self.machine, "edge", 2.3)
        self.assertIsNone(waiting_for_cooldown["selected_app"])
        selected = self.machine.select_tile_click("edge", now=3.81)
        self.assertEqual(selected["selected_app"].command, "OPEN_EDGE")

    def test_close_enters_closing_state_and_blocks_future_actions(self):
        self.machine.close()
        result = self.machine.process_frame("OPEN_PALM", now=1.0)
        self.assertEqual(result["mode"], InteractionMode.CLOSING.value)
        self.assertEqual(result["actions"], [])

    def test_success_keeps_camera_and_open_palm_rearms_next_app(self):
        self.machine.process_frame("OPEN_PALM", now=1.0)
        self._point(self.machine, "vscode", 2.0)
        self.machine.select_tile_click("vscode", now=2.0)
        self.assertEqual(self.machine.mode, InteractionMode.APP_LAUNCHING)
        self.machine.launch_completed(True)
        self.assertEqual(self.machine.mode, InteractionMode.DESKTOP_MODE)

        self.machine.process_frame("OPEN_PALM", now=2.1)
        next_app = self._point(self.machine, "explorer", 2.2)
        self.assertEqual(next_app["hovered_app"], "explorer")
        self.assertIsNone(next_app["selected_app"])
        selected = self.machine.select_tile_click("explorer", now=2.3)
        self.assertEqual(selected["selected_app"].command, "OPEN_EXPLORER")

    def test_default_smoothing_is_responsive(self):
        machine = DesktopInteractionStateMachine((1920, 1080))
        self.assertEqual(machine.cursor_smoother.alpha, 0.82)
        self.assertEqual(machine.cursor_smoother.deadzone_px, 0.8)


if __name__ == "__main__":
    unittest.main()
