import unittest
from unittest.mock import Mock, call

from vision_engine.air_mouse import left_click, move_system_cursor


class TestAirMouse(unittest.TestCase):
    def test_moves_native_cursor_with_monitor_origin(self):
        cursor_api = Mock()
        moved = move_system_cursor(
            (320, 240), cursor_api=cursor_api, screen_origin=(-1920, 40)
        )
        self.assertTrue(moved)
        cursor_api.setPos.assert_called_once_with(-1600, 280)

    def test_missing_point_does_not_move_cursor(self):
        cursor_api = Mock()
        self.assertFalse(move_system_cursor(None, cursor_api=cursor_api))
        cursor_api.setPos.assert_not_called()

    def test_one_left_click_sends_down_then_up(self):
        user32 = Mock()
        self.assertTrue(left_click(user32=user32))
        self.assertEqual(
            user32.mouse_event.call_args_list,
            [
                call(0x0002, 0, 0, 0, 0),
                call(0x0004, 0, 0, 0, 0),
            ],
        )


if __name__ == "__main__":
    unittest.main()
