import unittest
from unittest.mock import Mock

from vision_engine.desktop_overlay import (
    DESKTOP_TILES,
    DesktopOverlayController,
    OverlayState,
    compute_dock_tile_rects,
    map_normalized_to_screen,
)
from vision_engine.virtual_interface import CursorSmoother


class FakeOverlay:
    def __init__(self):
        self.visible = False
        self.cursor = None
        self.hovered = None
        self.status = ""
        self.close_calls = 0

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def update_cursor(self, point):
        self.cursor = point

    def set_hovered(self, tile_id):
        self.hovered = tile_id

    def set_status(self, text):
        self.status = text

    def close(self):
        self.close_calls += 1
        self.visible = False


class TestDesktopOverlayController(unittest.TestCase):
    def setUp(self):
        self.overlay = FakeOverlay()
        self.launch = Mock(return_value="app launched")
        self.controller = DesktopOverlayController(
            overlay=self.overlay,
            launch_command=self.launch,
            screen_size=(1000, 700),
            # Keep hover-boundary tests deterministic; production uses the
            # controller's smoothed cursor by default.
            cursor_smoother=CursorSmoother(alpha=1.0, deadzone_px=0.0),
        )

    def _tile_center_as_normalized(self, tile_id):
        x1, y1, x2, y2 = self.controller.tile_rects[tile_id]
        return (
            ((x1 + x2) / 2) / (self.controller.screen_width - 1),
            ((y1 + y2) / 2) / (self.controller.screen_height - 1),
        )

    def _show(self, now=1.0):
        result = self.controller.process_frame(
            "OPEN_PALM", tracking_available=True, now=now
        )
        self.assertTrue(self.overlay.visible)
        self.assertEqual(result["state"], "VISIBLE")

    def _point_at(self, tile_id, now):
        return self.controller.process_frame(
            "POINTING",
            pointer_xy=self._tile_center_as_normalized(tile_id),
            tracking_available=True,
            now=now,
        )

    def test_open_palm_shows_overlay(self):
        result = self.controller.process_frame(
            "OPEN_PALM", tracking_available=True, now=1.0
        )
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.controller.state, OverlayState.VISIBLE)
        self.assertEqual(result["state"], "VISIBLE")

    def test_fist_hides_overlay_without_show_desktop(self):
        self._show()
        self._point_at("desktop", 1.1)
        result = self.controller.process_frame(
            "FIST", tracking_available=True, now=1.2
        )
        self.assertFalse(self.overlay.visible)
        self.assertEqual(self.controller.state, OverlayState.HIDDEN)
        self.assertFalse(result["selected"])
        self.launch.assert_not_called()

    def test_pointing_maps_index_cursor_and_starts_hover(self):
        self._show()
        self._point_at("calculator", 2.0)
        self.assertEqual(self.overlay.hovered, "calculator")
        self.assertEqual(self.controller.state, OverlayState.HOVERING)
        self.assertIsNotNone(self.overlay.cursor)
        self.assertEqual(self.controller.hover_started_at, 2.0)

    def test_cursor_smoothing_reduces_motion_jitter(self):
        smoother = CursorSmoother(alpha=0.38, deadzone_px=0.0)
        smoother.update((100, 100))
        moved = smoother.update((200, 200))
        self.assertGreater(moved[0], 100)
        self.assertLess(moved[0], 200)
        self.assertEqual(moved[0], moved[1])

    def test_hover_under_500ms_does_not_launch(self):
        self._show()
        self._point_at("notepad", 1.0)
        result = self._point_at("notepad", 1.499)
        self.assertFalse(result["selected"])
        self.launch.assert_not_called()

    def test_hovering_500ms_launches_exactly_once_without_pinch(self):
        self._show()
        self._point_at("vscode", 1.0)
        result = self._point_at("vscode", 1.5)
        held = self._point_at("vscode", 2.0)
        self.assertTrue(result["selected"])
        self.assertEqual(result["command"], "OPEN_VSCODE")
        self.assertFalse(held["selected"])
        self.launch.assert_called_once_with("OPEN_VSCODE")

    def test_all_action_tiles_dispatch_their_configured_command(self):
        for tile in DESKTOP_TILES:
            if tile.command == "EXIT_APP":
                continue
            with self.subTest(tile=tile.tile_id):
                overlay = FakeOverlay()
                launch = Mock(return_value="queued")
                controller = DesktopOverlayController(
                    overlay=overlay,
                    launch_command=launch,
                    screen_size=(1000, 700),
                    cursor_smoother=CursorSmoother(alpha=1.0, deadzone_px=0.0),
                )
                rect = controller.tile_rects[tile.tile_id]
                pointer = (
                    ((rect[0] + rect[2]) / 2) / (controller.screen_width - 1),
                    ((rect[1] + rect[3]) / 2) / (controller.screen_height - 1),
                )
                controller.process_frame("OPEN_PALM", now=1.0)
                controller.process_frame(
                    "POINTING", pointer_xy=pointer, now=1.1
                )
                result = controller.process_frame(
                    "POINTING", pointer_xy=pointer, now=1.6
                )

                self.assertTrue(result["selected"])
                self.assertEqual(result["command"], tile.command)
                launch.assert_called_once_with(tile.command)

    def test_pinch_gesture_does_not_select_or_launch(self):
        self._show()
        self._point_at("explorer", 1.0)
        result = self.controller.process_frame(
            "PINCH", tracking_available=True, now=1.5
        )
        self.assertFalse(result["selected"])
        self.assertIsNone(self.overlay.hovered)
        self.launch.assert_not_called()

    def test_leaving_icon_cancels_timer(self):
        self._show()
        self._point_at("calculator", 1.0)
        self.controller.process_frame(
            "POINTING", pointer_xy=(0.0, 0.0), tracking_available=True, now=1.3
        )
        self.assertIsNone(self.controller.hover_started_at)
        self._point_at("calculator", 1.31)
        early = self._point_at("calculator", 1.809)
        launch = self._point_at("calculator", 1.81)
        self.assertFalse(early["selected"])
        self.assertTrue(launch["selected"])
        self.launch.assert_called_once_with("OPEN_CALCULATOR")

    def test_reentering_icon_allows_a_new_launch(self):
        self._show()
        self._point_at("explorer", 1.0)
        first = self._point_at("explorer", 1.5)
        self.assertTrue(first["selected"])
        self.controller.process_frame(
            "POINTING", pointer_xy=(0.0, 0.0), tracking_available=True, now=1.6
        )
        self._point_at("explorer", 2.0)
        early = self._point_at("explorer", 2.499)
        second = self._point_at("explorer", 2.5)
        self.assertFalse(early["selected"])
        self.assertTrue(second["selected"])
        self.assertEqual(self.launch.call_count, 2)
        self.assertEqual(self.launch.call_args_list[0].args, ("OPEN_EXPLORER",))
        self.assertEqual(self.launch.call_args_list[1].args, ("OPEN_EXPLORER",))

    def test_unknown_cancels_hover_and_never_launches(self):
        self._show()
        self._point_at("vscode", 1.0)
        result = self.controller.process_frame(
            "UNKNOWN", tracking_available=True, now=1.5
        )
        self.assertFalse(result["selected"])
        self.assertIsNone(self.controller.hover_started_at)
        self.launch.assert_not_called()

    def test_tracking_loss_cancels_hover_and_never_launches(self):
        self._show()
        self._point_at("vscode", 1.0)
        result = self.controller.process_frame(
            "POINTING",
            pointer_xy=self._tile_center_as_normalized("vscode"),
            tracking_available=False,
            now=1.5,
        )
        self.assertFalse(result["selected"])
        self.assertIsNone(self.overlay.hovered)
        self.assertIsNone(self.controller.hover_started_at)
        self.launch.assert_not_called()

    def test_exit_tile_closes_overlay_after_hover_delay(self):
        self._show()
        self._point_at("exit", 1.0)
        result = self._point_at("exit", 1.5)
        self.assertTrue(result["stop_requested"])
        self.assertEqual(self.controller.state, OverlayState.CLOSING)
        self.assertEqual(self.overlay.close_calls, 1)
        self.launch.assert_not_called()

    def test_shutdown_releases_overlay_once(self):
        self._show()
        self.controller.shutdown()
        self.controller.shutdown()
        self.assertEqual(self.controller.state, OverlayState.CLOSING)
        self.assertEqual(self.overlay.close_calls, 1)

    def test_normalized_mapping_respects_mirrored_frame(self):
        self.assertEqual(map_normalized_to_screen(0.0, 0.0, 1920, 1080), (0, 0))
        self.assertEqual(map_normalized_to_screen(1.0, 1.0, 1920, 1080), (1919, 1079))
        self.assertEqual(
            map_normalized_to_screen(0.0, 0.5, 1920, 1080, mirrored=False)[0],
            1919,
        )

    def test_native_dock_lists_all_requested_tiles(self):
        self.assertEqual(
            [tile.label for tile in DESKTOP_TILES],
            ["VS Code", "File Explorer", "Calculator", "Notepad", "Show Desktop", "Exit UI"],
        )
        self.assertEqual(len(compute_dock_tile_rects(1920, 1080)), 6)


if __name__ == "__main__":
    unittest.main()
