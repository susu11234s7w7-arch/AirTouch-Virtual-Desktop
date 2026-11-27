import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from vision_engine.desktop_interaction import DEFAULT_APPS
from vision_engine.qt_floating_launcher import (
    CameraPreviewWindow,
    FloatingLauncherWindow,
)


class TestQtFloatingLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = FloatingLauncherWindow(QRect(0, 0, 1920, 1080))

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_frameless_topmost_transparent_shape_has_only_tile_and_exit_regions(self):
        flags = self.window.windowFlags()
        self.assertTrue(flags & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(flags & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(
            self.window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        )
        self.assertEqual(len(self.window.tile_rects), 5)
        self.assertFalse(self.window.mask().contains(QPoint(20, 20)))
        chrome = self.window.tile_rects["chrome"]
        self.assertTrue(
            self.window.mask().contains(QPoint((chrome[0] + chrome[2]) // 2, (chrome[1] + chrome[3]) // 2))
        )
        self.assertTrue(self.window.mask().contains(self.window.exit_rect.center()))

    def test_mouse_click_selects_the_tile_and_exit_ui(self):
        selected = []
        exited = []
        self.window.appSelected.connect(selected.append)
        self.window.exitRequested.connect(lambda: exited.append(True))
        self.window.show()
        self.app.processEvents()

        chrome = self.window.tile_rects["chrome"]
        chrome_point = QPoint((chrome[0] + chrome[2]) // 2, (chrome[1] + chrome[3]) // 2)
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, pos=chrome_point)
        self.assertEqual(selected, ["chrome"])

        exit_point = self.window.exit_rect.center()
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, pos=exit_point)
        self.assertEqual(exited, [True])

    def test_closing_preview_hides_only_its_window(self):
        preview = CameraPreviewWindow()
        preview.show()
        self.app.processEvents()
        preview.close()
        self.app.processEvents()
        self.assertFalse(preview.isVisible())
        self.assertTrue(self.app.closingDown() is False)
        preview.deleteLater()


if __name__ == "__main__":
    unittest.main()
