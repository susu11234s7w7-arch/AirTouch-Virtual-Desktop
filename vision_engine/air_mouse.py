"""Small Windows mouse bridge used by the UI thread for air-mouse input."""

import ctypes
import os


def move_system_cursor(point, cursor_api=None, screen_origin=(0, 0)):
    """Move the native pointer to a screen-local point, preserving monitor origin."""
    if point is None:
        return False
    if cursor_api is None:
        from PySide6.QtGui import QCursor

        cursor_api = QCursor
    x = int(point[0]) + int(screen_origin[0])
    y = int(point[1]) + int(screen_origin[1])
    cursor_api.setPos(x, y)
    return True


def left_click(user32=None):
    """Send one native left-button click at the current pointer position."""
    if user32 is None:
        if os.name != "nt":
            return False
        user32 = ctypes.windll.user32

    mouseeventf_leftdown = 0x0002
    mouseeventf_leftup = 0x0004
    user32.mouse_event(mouseeventf_leftdown, 0, 0, 0, 0)
    user32.mouse_event(mouseeventf_leftup, 0, 0, 0, 0)
    return True
