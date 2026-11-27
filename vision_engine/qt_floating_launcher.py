"""PySide6 floating launcher and independent camera preview windows."""

from pathlib import Path
import os

from PySide6.QtCore import (
    QEasingCurve,
    QFileInfo,
    QPoint,
    QRect,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPolygon,
    QPixmap,
    QRegion,
)
from PySide6.QtWidgets import (
    QFileIconProvider,
    QLabel,
    QMainWindow,
    QWidget,
)

from vision_engine.desktop_interaction import DEFAULT_APPS, compute_arc_tile_rects


def _application_path(tile_id):
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    windows_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidates = {
        "chrome": (
            program_files / "Google/Chrome/Application/chrome.exe",
            program_files_x86 / "Google/Chrome/Application/chrome.exe",
            local_app_data / "Google/Chrome/Application/chrome.exe",
        ),
        "vscode": (
            local_app_data / "Programs/Microsoft VS Code/Code.exe",
            program_files / "Microsoft VS Code/Code.exe",
            program_files_x86 / "Microsoft VS Code/Code.exe",
        ),
        "explorer": (windows_root / "explorer.exe",),
        "edge": (
            program_files / "Microsoft/Edge/Application/msedge.exe",
            program_files_x86 / "Microsoft/Edge/Application/msedge.exe",
        ),
        "settings": (windows_root / "ImmersiveControlPanel/SystemSettings.exe",),
    }
    for path in candidates.get(tile_id, ()):
        if path.is_file():
            return str(path)
    return None


class FloatingLauncherWindow(QWidget):
    """Topmost translucent arc. Its shaped region only covers app cards/exit."""

    appSelected = Signal(str)
    exitRequested = Signal()

    def __init__(self, screen_geometry, parent=None):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(parent, flags)
        self.screen_geometry = screen_geometry
        self.screen_width = int(screen_geometry.width())
        self.screen_height = int(screen_geometry.height())
        self.setGeometry(screen_geometry)
        self.setWindowTitle("AirTouch Floating App Launcher")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self.tile_rects = compute_arc_tile_rects(self.screen_width, self.screen_height)
        self.exit_rect = QRect(max(12, self.screen_width - 112), 22, 96, 36)
        self.hovered_tile = None
        self.dwell_ready = False
        self.status = "Point with index; raise and lower middle finger to click"
        self._icons = self._load_native_icons()
        self._build_window_region()

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(230)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._finish_fade)
        self._hiding = False
        self.setWindowOpacity(0.0)
        self.hide()

    def _build_window_region(self):
        region = QRegion(self.exit_rect)
        for rect in self.tile_rects.values():
            x1, y1, x2, y2 = rect
            region = region.united(QRegion(QRect(x1, y1, x2 - x1, y2 - y1)))
        # Windows receives input only over cards and the explicit Exit UI control.
        # Transparent gaps remain available to the desktop beneath the launcher.
        self.setMask(region)

    def _load_native_icons(self):
        provider = QFileIconProvider()
        icons = {}
        for app in DEFAULT_APPS:
            path = _application_path(app.tile_id)
            if path:
                icon = provider.icon(QFileInfo(path))
                if not icon.isNull():
                    icons[app.tile_id] = icon
        return icons

    def show_animated(self):
        self._hiding = False
        self._fade.stop()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self.update()

    def hide_animated(self):
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            return
        self._hiding = True
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _finish_fade(self):
        if self._hiding:
            self.hide()
            self._hiding = False

    def set_air_state(self, hovered_tile, dwell_ready=False):
        self.hovered_tile = hovered_tile
        self.dwell_ready = bool(dwell_ready)
        self.update()

    def set_status(self, text):
        self.status = str(text)
        self.update()

    def _draw_fallback_icon(self, painter, app, center):
        painter.save()
        painter.setPen(QPen(QColor(235, 244, 255, 235), 3))
        font = QFont("Segoe UI", 22, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(QRect(center.x() - 34, center.y() - 30, 68, 60), Qt.AlignmentFlag.AlignCenter, app.fallback_glyph)
        painter.restore()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        for app in DEFAULT_APPS:
            x1, y1, x2, y2 = self.tile_rects[app.tile_id]
            rect = QRect(x1, y1, x2 - x1, y2 - y1)
            hovered = app.tile_id == self.hovered_tile
            bg = QColor(19, 31, 47, 218 if hovered else 178)
            border = QColor(*app.accent, 250 if hovered else 135)
            painter.setPen(QPen(border, 2 if hovered else 1))
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 26, 26)

            icon_center = QPoint(rect.center().x(), rect.top() + 55)
            circle_color = QColor(*app.accent, 210 if hovered else 150)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(circle_color)
            painter.drawEllipse(icon_center, 35 if hovered else 32, 35 if hovered else 32)

            icon = self._icons.get(app.tile_id)
            if icon is not None:
                pixmap = icon.pixmap(46, 46)
                painter.drawPixmap(
                    QRect(icon_center.x() - 23, icon_center.y() - 23, 46, 46),
                    pixmap,
                )
            else:
                self._draw_fallback_icon(painter, app, icon_center)

            if hovered:
                ring_color = QColor(104, 222, 255, 240 if self.dwell_ready else 175)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(ring_color, 3 if self.dwell_ready else 2))
                painter.drawEllipse(icon_center, 42, 42)

            painter.setPen(QColor(238, 245, 255, 245))
            font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.drawText(
                QRect(rect.left() + 5, rect.bottom() - 42, rect.width() - 10, 34),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                app.label,
            )

        painter.setPen(QPen(QColor(215, 232, 250, 210), 1))
        painter.setBrush(QColor(15, 25, 38, 225))
        painter.drawRoundedRect(self.exit_rect, 12, 12)
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.drawText(self.exit_rect, Qt.AlignmentFlag.AlignCenter, "×  Exit UI")

        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        point = event.position().toPoint()
        if self.exit_rect.contains(point):
            self.exitRequested.emit()
            return
        for tile_id, bounds in self.tile_rects.items():
            x1, y1, x2, y2 = bounds
            if QRect(x1, y1, x2 - x1, y2 - y1).contains(point):
                self.appSelected.emit(tile_id)
                return
        super().mousePressEvent(event)


class AirCursorWindow(QWidget):
    """Full-screen visual cursor that never intercepts desktop mouse input."""

    def __init__(self, screen_geometry, parent=None):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        super().__init__(parent, flags)
        self.screen_geometry = screen_geometry
        self.setGeometry(screen_geometry)
        self.setWindowTitle("AirTouch Air Cursor")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.cursor_local = None
        self.hide()

    def set_cursor_position(self, cursor_xy):
        if cursor_xy is None:
            self.hide_cursor()
            return
        self.cursor_local = QPoint(
            int(cursor_xy[0] - self.screen_geometry.x()),
            int(cursor_xy[1] - self.screen_geometry.y()),
        )
        if not self.isVisible():
            self.show()
            self.raise_()
        self.update()

    def hide_cursor(self):
        self.cursor_local = None
        self.hide()

    def paintEvent(self, _event):
        if self.cursor_local is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = self.cursor_local
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 207, 0, 62))
        painter.drawEllipse(center, 29, 29)
        painter.setBrush(QColor(255, 226, 92, 52))
        painter.drawEllipse(center, 21, 21)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        arrow = QPolygon(
            [
                center,
                center + QPoint(5, 30),
                center + QPoint(12, 23),
                center + QPoint(19, 35),
                center + QPoint(24, 32),
                center + QPoint(17, 20),
                center + QPoint(28, 18),
            ]
        )
        painter.setPen(QPen(QColor(74, 55, 0, 250), 2))
        painter.setBrush(QColor(255, 214, 0, 255))
        painter.drawPolygon(arrow)
        painter.end()


class CameraPreviewWindow(QMainWindow):
    """Foreground monitoring preview, hidden without stopping camera capture."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AirTouch Virtual Desktop - Camera Monitoring")
        self.setMinimumSize(820, 500)
        self.resize(1040, 640)
        self.preview = QLabel("Starting camera…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(
            "QLabel { background: #101821; color: #d9e5f2; font-size: 18px; }"
        )
        self.setCentralWidget(self.preview)

    def set_frame(self, image):
        pixmap = QPixmap.fromImage(image)
        if not pixmap.isNull():
            self.preview.setPixmap(
                pixmap.scaled(
                    self.preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def set_message(self, text):
        self.preview.setText(str(text))

    def closeEvent(self, event):
        # Closing the preview is a visibility action, never a camera shutdown.
        event.ignore()
        self.hide()
