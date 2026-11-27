"""Native, click-through Windows dock and gesture interaction state.

The native window is deliberately isolated from camera processing.  A dedicated
Win32 message thread owns the layered window; vision code publishes small state
snapshots without waiting for paint or animation work.
"""

from dataclasses import dataclass
from enum import Enum
import os
from queue import Queue
import threading
import time

from vision_engine.virtual_interface import CursorSmoother


class OverlayState(str, Enum):
    HIDDEN = "HIDDEN"
    VISIBLE = "VISIBLE"
    HOVERING = "HOVERING"
    SELECTING = "SELECTING"
    CLOSING = "CLOSING"


@dataclass(frozen=True)
class DesktopTile:
    tile_id: str
    label: str
    command: str
    icon: str
    accent: tuple


DESKTOP_TILES = (
    DesktopTile("vscode", "VS Code", "OPEN_VSCODE", "VS", (90, 170, 255)),
    DesktopTile("explorer", "File Explorer", "OPEN_EXPLORER", "▣", (80, 205, 255)),
    DesktopTile("calculator", "Calculator", "OPEN_CALCULATOR", "±", (120, 220, 160)),
    DesktopTile("notepad", "Notepad", "OPEN_NOTEPAD", "N", (245, 195, 100)),
    DesktopTile("desktop", "Show Desktop", "MINIMIZE_ALL", "▱", (190, 145, 255)),
    DesktopTile("exit", "Exit UI", "EXIT_APP", "×", (255, 115, 135)),
)


class BackgroundCommandLauncher:
    """Serialize application launches away from the camera-processing loop."""

    def __init__(self, execute_command):
        self.execute_command = execute_command
        self._queue = Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="AirTouchAppLauncher",
            daemon=True,
        )
        self._thread.start()

    def submit(self, command):
        with self._lock:
            if self._closed:
                return "Launcher is shutting down"
            self._queue.put(str(command))
        return f"Queued {command}"

    def _run(self):
        while True:
            command = self._queue.get()
            if command is None:
                return
            try:
                self.execute_command(command)
            except Exception as exc:
                print(f"[BACKGROUND LAUNCH ERROR] {command}: {exc}")

    def close(self, timeout=0.25):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._queue.put(None)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout)


def map_normalized_to_screen(x, y, screen_width, screen_height, mirrored=True):
    """Map camera coordinates to primary-screen pixels.

    The production camera frame is flipped before MediaPipe sees it, so its
    normalized x coordinate is already in user-facing, left-to-right order.
    """
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


def compute_dock_tile_rects(screen_width, screen_height):
    """Return screen-coordinate tile rectangles for the lower-center dock."""
    width = max(320, min(960, int(screen_width) - 48))
    width = min(width, int(screen_width))
    panel_height = 154
    panel_x = (int(screen_width) - width) // 2
    panel_y = max(8, int(screen_height) - panel_height - 30)
    inset = 18
    gap = 8
    tile_y1 = panel_y + 54
    tile_y2 = panel_y + 137
    tile_width = (width - 2 * inset - gap * (len(DESKTOP_TILES) - 1)) / len(DESKTOP_TILES)
    return {
        tile.tile_id: (
            int(round(panel_x + inset + index * (tile_width + gap))),
            tile_y1,
            int(round(panel_x + inset + index * (tile_width + gap) + tile_width)),
            tile_y2,
        )
        for index, tile in enumerate(DESKTOP_TILES)
    }


class DesktopOverlayController:
    """Gesture-to-overlay state machine, independent of the native GUI backend."""

    def __init__(
        self,
        overlay,
        launch_command,
        screen_size,
        cursor_smoother=None,
        tiles=DESKTOP_TILES,
    ):
        self.overlay = overlay
        self.launch_command = launch_command
        self.screen_width, self.screen_height = map(int, screen_size)
        self.cursor_smoother = cursor_smoother or CursorSmoother(alpha=0.38, deadzone_px=2.0)
        self.tiles = {tile.tile_id: tile for tile in tiles}
        self.tile_rects = compute_dock_tile_rects(self.screen_width, self.screen_height)
        self.state = OverlayState.HIDDEN
        self.hovered_id = None
        self.cursor_xy = None
        self.hover_seconds = 0.5
        self.hover_started_at = None
        self._fired_current_hover = False
        self.last_action = None

    @property
    def visible(self):
        return self.state in (OverlayState.VISIBLE, OverlayState.HOVERING, OverlayState.SELECTING)

    def show(self):
        if self.state == OverlayState.CLOSING:
            return
        if self.state == OverlayState.HIDDEN:
            self.overlay.show()
            self.state = OverlayState.VISIBLE
        self._clear_hover()
        self.overlay.set_status("Point at an app to launch automatically")

    def hide(self):
        if self.state == OverlayState.CLOSING:
            return
        if self.state != OverlayState.HIDDEN:
            self.overlay.hide()
        self.state = OverlayState.HIDDEN
        self._clear_hover()
        self.overlay.set_status("")

    def _clear_hover(self):
        self.hovered_id = None
        self.cursor_xy = None
        self.hover_started_at = None
        self._fired_current_hover = False
        self.cursor_smoother.reset()
        self.overlay.update_cursor(None)
        self.overlay.set_hovered(None)

    def _hit_test(self, point):
        if point is None:
            return None
        px, py = point
        for tile_id, (x1, y1, x2, y2) in self.tile_rects.items():
            if x1 <= px <= x2 and y1 <= py <= y2:
                return tile_id
        return None

    def _point(self, normalized_xy, now):
        if normalized_xy is None:
            self._clear_hover()
            self.state = OverlayState.VISIBLE
            return None
        raw = map_normalized_to_screen(
            normalized_xy[0],
            normalized_xy[1],
            self.screen_width,
            self.screen_height,
            mirrored=True,
        )
        point = self.cursor_smoother.update(raw)
        self.cursor_xy = point
        target_id = self._hit_test(point)
        if target_id != self.hovered_id:
            self.hovered_id = target_id
            self.hover_started_at = now if target_id is not None else None
            self._fired_current_hover = False
        self.overlay.update_cursor(point)
        self.overlay.set_hovered(target_id)
        self.state = OverlayState.HOVERING if self.hovered_id else OverlayState.VISIBLE
        if (
            target_id is not None
            and not self._fired_current_hover
            and self.hover_started_at is not None
            and now - self.hover_started_at >= self.hover_seconds
        ):
            return self._launch_hovered()
        return None

    def _launch_hovered(self):
        tile = self.tiles.get(self.hovered_id)
        if (
            tile is None
            or self.state != OverlayState.HOVERING
            or self._fired_current_hover
        ):
            return None

        # Consume this hover before dispatching. Even a slow launcher cannot
        # produce a second event until the cursor leaves and re-enters.
        self._fired_current_hover = True
        self.state = OverlayState.SELECTING
        self.overlay.set_status(f"Opening {tile.label}...")
        if tile.command == "EXIT_APP":
            self.shutdown()
            self.last_action = "EXIT_APP"
            return {"selected": True, "command": "EXIT_APP", "stop_requested": True}

        try:
            result = self.launch_command(tile.command)
            self.last_action = tile.command
            self.overlay.set_status(str(result))
            return {
                "selected": True,
                "command": tile.command,
                "result": result,
                "stop_requested": False,
            }
        except Exception as exc:
            self.overlay.set_status(f"Could not open {tile.label}: {exc}")
            return {
                "selected": True,
                "command": tile.command,
                "result": str(exc),
                "stop_requested": False,
            }
        finally:
            if self.state != OverlayState.CLOSING:
                self.state = OverlayState.HOVERING

    def process_frame(
        self,
        gesture,
        pointer_xy=None,
        tracking_available=True,
        command=None,
        now=None,
    ):
        """Apply one stabilized camera frame and return any action metadata."""
        now = time.monotonic() if now is None else now
        gesture = gesture.strip().upper() if isinstance(gesture, str) else "UNKNOWN"
        outcome = {"selected": False, "stop_requested": False, "state": self.state.value}

        if self.state == OverlayState.CLOSING:
            outcome["stop_requested"] = True
            return outcome

        # The gesture controller emits these actions only on stabilized changes.
        if command == "SHOW_OVERLAY" or (
            gesture == "OPEN_PALM" and self.state == OverlayState.HIDDEN
        ):
            self.show()
        elif command == "HIDE_OVERLAY" or (gesture == "FIST" and self.visible):
            self.hide()
            outcome["state"] = self.state.value
            return outcome

        if not tracking_available:
            if self.visible:
                self._clear_hover()
                self.state = OverlayState.VISIBLE
            outcome["state"] = self.state.value
            return outcome

        if gesture == "FIST":
            if self.visible:
                self.hide()
        elif gesture == "OPEN_PALM":
            # Clear any old target while an open hand is being held.
            if self.visible:
                self._clear_hover()
                self.state = OverlayState.VISIBLE
        elif gesture == "UNKNOWN":
            if self.visible:
                self._clear_hover()
                self.state = OverlayState.VISIBLE
        elif gesture == "POINTING":
            if self.visible:
                launch_result = self._point(pointer_xy, now)
                if launch_result is not None:
                    outcome.update(launch_result)
        else:
            if self.visible:
                self._clear_hover()
                self.state = OverlayState.VISIBLE

        outcome["state"] = self.state.value
        return outcome

    def shutdown(self):
        if self.state == OverlayState.CLOSING:
            return
        self.state = OverlayState.CLOSING
        self.hovered_id = None
        self.cursor_xy = None
        self.overlay.close()


class WindowsDesktopOverlay:
    """Click-through Win32 layered window with an animated glass-style app dock."""

    _message = 0x8001  # WM_APP + 1

    def __init__(self, fade_step=30, fade_interval_ms=16):
        self.fade_step = max(1, int(fade_step))
        self.fade_interval_ms = max(1, int(fade_interval_ms))
        self.screen_size = get_windows_screen_size()
        self._lock = threading.Lock()
        self._state = {
            "visible": False,
            "cursor": None,
            "hovered": None,
            "status": "",
        }
        self._pending_wake = False
        self._thread = None
        self._thread_id = None
        self._hwnd = None
        self._started = False
        self._closing = False
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._startup_error = None

    def start(self, timeout=5.0):
        if self._started:
            return self
        if os.name != "nt":
            raise OSError("The native desktop overlay requires Windows.")
        self._started = True
        self._thread = threading.Thread(
            target=self._message_loop,
            name="AirTouchDesktopOverlay",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            self.close()
            raise TimeoutError("Timed out starting the native desktop overlay.")
        if self._startup_error is not None:
            raise RuntimeError("Could not start the native desktop overlay") from self._startup_error
        return self

    def show(self):
        self._publish(visible=True)

    def hide(self):
        self._publish(visible=False, cursor=None, hovered=None)

    def update_cursor(self, point):
        self._publish(cursor=point)

    def set_hovered(self, tile_id):
        self._publish(hovered=tile_id)

    def set_status(self, text):
        self._publish(status=str(text))

    def _publish(self, **updates):
        if self._closing or not self._started:
            return
        with self._lock:
            self._state.update(updates)
            should_wake = not self._pending_wake
            self._pending_wake = True
        if should_wake and self._thread_id:
            _native().user32.PostThreadMessageW(
                self._thread_id, self._message, 0, 0
            )

    def close(self, timeout=3.0):
        if self._closing:
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout)
            return
        self._closing = True
        if self._thread_id:
            _native().user32.PostThreadMessageW(
                self._thread_id, _native().WM_CLOSE, 0, 0
            )
        if self._thread is not None and threading.current_thread() is not self._thread:
            self._thread.join(timeout)

    def _message_loop(self):
        try:
            _run_native_overlay(self)
        except BaseException as exc:
            self._startup_error = exc
        finally:
            self._ready.set()
            self._closed.set()


def get_windows_screen_size():
    """Return primary screen dimensions, or a harmless test default off Windows."""
    if os.name != "nt":
        return (1280, 720)
    user32 = _native().user32
    return (int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1)))


def _native():
    """Create configured Win32 API bindings lazily so importing is cross-platform."""
    if os.name != "nt":
        raise OSError("Win32 APIs are only available on Windows.")
    return _Win32


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _LRESULT = ctypes.c_ssize_t
    _WNDPROC = ctypes.WINFUNCTYPE(
        _LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", _POINT),
        ]

    class _PAINTSTRUCT(ctypes.Structure):
        _fields_ = [
            ("hdc", wintypes.HDC),
            ("fErase", wintypes.BOOL),
            ("rcPaint", _RECT),
            ("fRestore", wintypes.BOOL),
            ("fIncUpdate", wintypes.BOOL),
            ("rgbReserved", ctypes.c_byte * 32),
        ]

    class _WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", _WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    class _Win32:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        kernel32 = ctypes.windll.kernel32

        WM_PAINT = 0x000F
        WM_CLOSE = 0x0010
        WM_DESTROY = 0x0002
        WM_TIMER = 0x0113
        WM_NCHITTEST = 0x0084
        HTTRANSPARENT = -1
        WM_QUIT = 0x0012
        WM_APP = 0x8000
        WS_POPUP = 0x80000000
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_TOPMOST = 0x00000008
        WS_EX_NOACTIVATE = 0x08000000
        SW_HIDE = 0
        SW_SHOWNOACTIVATE = 4
        HWND_TOPMOST = ctypes.c_void_p(-1)
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        LWA_COLORKEY = 0x00000001
        LWA_ALPHA = 0x00000002
        TRANSPARENT = 1
        DT_CENTER = 0x00000001
        DT_VCENTER = 0x00000004
        DT_SINGLELINE = 0x00000020
        DT_END_ELLIPSIS = 0x00008000
        FW_NORMAL = 400
        FW_SEMIBOLD = 600
        COLOR_KEY = (255, 0, 255)

        user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = _LRESULT
        user32.GetMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = ctypes.c_int
        user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostThreadMessageW.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(_RECT), wintypes.HBRUSH]
        user32.FillRect.restype = ctypes.c_int
        user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
        user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
        user32.SetTimer.restype = ctypes.c_size_t
        user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
        user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(_PAINTSTRUCT)]
        user32.BeginPaint.restype = wintypes.HDC
        user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(_PAINTSTRUCT)]
        user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT), wintypes.BOOL]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
        gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.RoundRect.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi32.Rectangle.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi32.Ellipse.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi32.Ellipse.restype = wintypes.BOOL
        gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
        gdi32.CreatePen.restype = wintypes.HPEN
        gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
        gdi32.CreateFontW.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPCWSTR,
        ]
        gdi32.CreateFontW.restype = wintypes.HFONT
        user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(_RECT), wintypes.UINT]
        user32.DrawTextW.restype = ctypes.c_int
        gdi32.GetStockObject.argtypes = [ctypes.c_int]
        gdi32.GetStockObject.restype = wintypes.HGDIOBJ


def _colorref(rgb):
    return int(rgb[0]) | (int(rgb[1]) << 8) | (int(rgb[2]) << 16)


def _run_native_overlay(overlay):
    """Create the layered window and pump its message queue on the owner thread."""
    import ctypes
    from ctypes import wintypes

    native = _native()
    user32 = native.user32
    gdi32 = native.gdi32
    class_name = "AirTouchNativeDesktopOverlay"
    instance = native.kernel32.GetModuleHandleW(None)
    overlay._thread_id = int(threading.get_native_id())

    # Force creation of this thread's Windows message queue before callers post.
    msg = _MSG()
    user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

    def draw_text(hdc, text, rect, color=(240, 245, 255), font_size=16, weight=native.FW_NORMAL, face="Segoe UI"):
        font = gdi32.CreateFontW(-font_size, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 4, 0, face)
        old_font = gdi32.SelectObject(hdc, font)
        gdi32.SetTextColor(hdc, _colorref(color))
        gdi32.SetBkMode(hdc, native.TRANSPARENT)
        r = _RECT(*rect)
        user32.DrawTextW(hdc, str(text), -1, ctypes.byref(r), native.DT_CENTER | native.DT_VCENTER | native.DT_SINGLELINE | native.DT_END_ELLIPSIS)
        gdi32.SelectObject(hdc, old_font)
        gdi32.DeleteObject(font)

    def fill_round(hdc, rect, rgb, radius=16, outline=None, outline_width=1):
        brush = gdi32.CreateSolidBrush(_colorref(rgb))
        old_brush = gdi32.SelectObject(hdc, brush)
        old_pen = gdi32.SelectObject(hdc, gdi32.GetStockObject(8))  # NULL_PEN
        gdi32.RoundRect(hdc, rect[0], rect[1], rect[2], rect[3], radius, radius)
        gdi32.SelectObject(hdc, old_pen)
        gdi32.SelectObject(hdc, old_brush)
        gdi32.DeleteObject(brush)
        if outline is not None:
            pen = gdi32.CreatePen(0, outline_width, _colorref(outline))
            old_pen = gdi32.SelectObject(hdc, pen)
            old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # HOLLOW_BRUSH
            gdi32.RoundRect(hdc, rect[0], rect[1], rect[2], rect[3], radius, radius)
            gdi32.SelectObject(hdc, old_brush)
            gdi32.SelectObject(hdc, old_pen)
            gdi32.DeleteObject(pen)

    def paint(hwnd):
        ps = _PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        width, height = overlay.screen_size
        key_brush = gdi32.CreateSolidBrush(_colorref(native.COLOR_KEY))
        client_rect = _RECT(0, 0, width, height)
        user32.FillRect(hdc, ctypes.byref(client_rect), key_brush)
        gdi32.DeleteObject(key_brush)

        with overlay._lock:
            snapshot = dict(overlay._state)

        dock_width = max(320, min(960, width - 48))
        dock_width = min(dock_width, width)
        panel_x = (width - dock_width) // 2
        panel_y = max(8, height - 154 - 30)
        panel = (panel_x, panel_y, panel_x + dock_width, panel_y + 154)
        fill_round(hdc, panel, (28, 37, 54), radius=28, outline=(93, 122, 157), outline_width=2)
        fill_round(hdc, (panel_x + 2, panel_y + 2, panel_x + dock_width - 2, panel_y + 48), (36, 49, 68), radius=24)
        draw_text(hdc, "AIRTOUCH  /  DESKTOP DOCK", (panel_x + 20, panel_y + 8, panel_x + dock_width - 20, panel_y + 31), (174, 213, 245), 13, native.FW_SEMIBOLD)
        status = snapshot.get("status") or "Point at an app to launch automatically"
        draw_text(hdc, status, (panel_x + 20, panel_y + 29, panel_x + dock_width - 20, panel_y + 48), (160, 180, 202), 11)

        inset, gap = 18, 8
        tile_y1, tile_y2 = panel_y + 54, panel_y + 137
        tile_width = (dock_width - 2 * inset - gap * (len(DESKTOP_TILES) - 1)) / len(DESKTOP_TILES)
        for index, tile in enumerate(DESKTOP_TILES):
            x1 = int(round(panel_x + inset + index * (tile_width + gap)))
            x2 = int(round(panel_x + inset + index * (tile_width + gap) + tile_width))
            hovered = snapshot.get("hovered") == tile.tile_id
            bg = (47, 63, 84) if hovered else (35, 46, 63)
            rect = (x1, tile_y1, x2, tile_y2)
            fill_round(hdc, rect, bg, radius=17, outline=tile.accent if hovered else (68, 88, 113), outline_width=2 if hovered else 1)
            icon_rect = (x1 + 7, tile_y1 + 7, x2 - 7, tile_y1 + 45)
            draw_text(hdc, tile.icon, icon_rect, tile.accent, 22 if tile.icon != "VS" else 17, native.FW_SEMIBOLD)
            draw_text(hdc, tile.label, (x1 + 4, tile_y1 + 47, x2 - 4, tile_y2 - 5), (247, 249, 253), 11, native.FW_SEMIBOLD if hovered else native.FW_NORMAL)

        cursor = snapshot.get("cursor")
        if cursor is not None:
            cx, cy = map(int, cursor)
            ring = gdi32.CreatePen(0, 3, _colorref((116, 224, 255)))
            old_pen = gdi32.SelectObject(hdc, ring)
            old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(5))
            gdi32.Ellipse(hdc, cx - 13, cy - 13, cx + 13, cy + 13)
            gdi32.SelectObject(hdc, old_brush)
            gdi32.SelectObject(hdc, old_pen)
            gdi32.DeleteObject(ring)
            dot = gdi32.CreateSolidBrush(_colorref((224, 251, 255)))
            old_brush = gdi32.SelectObject(hdc, dot)
            gdi32.Ellipse(hdc, cx - 3, cy - 3, cx + 3, cy + 3)
            gdi32.SelectObject(hdc, old_brush)
            gdi32.DeleteObject(dot)

        user32.EndPaint(hwnd, ctypes.byref(ps))

    def apply_latest(hwnd):
        with overlay._lock:
            snapshot = dict(overlay._state)
            overlay._pending_wake = False
        requested_visible = bool(snapshot["visible"])
        if requested_visible and not overlay._target_visible:
            overlay._target_visible = True
            overlay._alpha = 0
            user32.ShowWindow(hwnd, native.SW_SHOWNOACTIVATE)
            user32.SetWindowPos(hwnd, native.HWND_TOPMOST, 0, 0, 0, 0, native.SWP_NOMOVE | native.SWP_NOSIZE | native.SWP_NOACTIVATE | native.SWP_SHOWWINDOW)
            user32.SetTimer(hwnd, 1, overlay.fade_interval_ms, None)
        elif not requested_visible and overlay._target_visible:
            overlay._target_visible = False
            user32.SetTimer(hwnd, 1, overlay.fade_interval_ms, None)
        user32.InvalidateRect(hwnd, None, False)

    @_WNDPROC
    def wnd_proc(hwnd, message, wparam, lparam):
        if message == overlay._message:
            apply_latest(hwnd)
            return 0
        if message == native.WM_PAINT:
            paint(hwnd)
            return 0
        if message == native.WM_TIMER and wparam == 1:
            if overlay._target_visible:
                overlay._alpha = min(238, overlay._alpha + overlay.fade_step)
            else:
                overlay._alpha = max(0, overlay._alpha - overlay.fade_step)
            user32.SetLayeredWindowAttributes(hwnd, _colorref(native.COLOR_KEY), overlay._alpha, native.LWA_COLORKEY | native.LWA_ALPHA)
            user32.InvalidateRect(hwnd, None, False)
            if overlay._target_visible and overlay._alpha >= 238:
                user32.KillTimer(hwnd, 1)
            elif not overlay._target_visible and overlay._alpha == 0:
                user32.KillTimer(hwnd, 1)
                user32.ShowWindow(hwnd, native.SW_HIDE)
            return 0
        if message == native.WM_NCHITTEST:
            return native.HTTRANSPARENT
        if message == native.WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if message == native.WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    wnd_class = _WNDCLASSW()
    wnd_class.lpfnWndProc = wnd_proc
    wnd_class.hInstance = instance
    wnd_class.lpszClassName = class_name
    if not user32.RegisterClassW(ctypes.byref(wnd_class)):
        error = ctypes.get_last_error()
        if error != 1410:  # ERROR_CLASS_ALREADY_EXISTS
            raise ctypes.WinError(error)

    width, height = overlay.screen_size
    ex_style = native.WS_EX_LAYERED | native.WS_EX_TRANSPARENT | native.WS_EX_TOOLWINDOW | native.WS_EX_TOPMOST | native.WS_EX_NOACTIVATE
    hwnd = user32.CreateWindowExW(ex_style, class_name, "AirTouch Desktop Overlay", native.WS_POPUP, 0, 0, width, height, None, None, instance, None)
    if not hwnd:
        raise ctypes.WinError(ctypes.get_last_error())

    overlay._hwnd = hwnd
    overlay._alpha = 0
    overlay._target_visible = False
    user32.SetLayeredWindowAttributes(hwnd, _colorref(native.COLOR_KEY), 0, native.LWA_COLORKEY | native.LWA_ALPHA)
    overlay._ready.set()

    message = _MSG()
    while True:
        result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
        if result <= 0:
            break
        if message.hwnd is None and message.message == native.WM_CLOSE:
            if overlay._hwnd:
                user32.DestroyWindow(overlay._hwnd)
                overlay._hwnd = None
            else:
                user32.PostQuitMessage(0)
            continue
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))

    if overlay._hwnd:
        user32.DestroyWindow(overlay._hwnd)
        overlay._hwnd = None
    user32.UnregisterClassW(class_name, instance)
