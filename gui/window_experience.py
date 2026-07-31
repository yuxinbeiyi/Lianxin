"""Persistent window modes, system tray integration and desktop notifications."""

from __future__ import annotations

from PyQt5.QtCore import QObject, QTimer, Qt
from PyQt5.QtWidgets import QAction, QApplication, QMenu, QSystemTrayIcon


class WindowExperienceController(QObject):
    def __init__(self, window, settings, *, mode_callback=None,
                 companion_callback=None, quit_callback=None, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.settings = settings
        self.mode_callback = mode_callback
        self.companion_callback = companion_callback
        self.quit_callback = quit_callback
        self.tray = None
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.timeout.connect(self.capture_geometry)
        self._create_tray()

    @property
    def tray_available(self) -> bool:
        return bool(self.tray and self.tray.isVisible())

    def _create_tray(self) -> None:
        if not self.settings.tray_enabled or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(self.window.windowIcon(), self)
        tray.setToolTip("莲心AI")
        menu = QMenu()
        show_action = QAction("显示莲心", menu)
        show_action.triggered.connect(self.show_main)
        normal_action = QAction("标准窗口", menu)
        normal_action.triggered.connect(lambda: self.set_mode("normal"))
        compact_action = QAction("紧凑聊天", menu)
        compact_action.triggered.connect(lambda: self.set_mode("compact"))
        companion_action = QAction("桌面陪伴", menu)
        companion_action.triggered.connect(lambda: self.set_mode("companion"))
        top_action = QAction("始终置顶", menu)
        top_action.setCheckable(True)
        top_action.setChecked(self.settings.always_on_top)
        top_action.toggled.connect(self.set_always_on_top)
        quit_action = QAction("退出莲心", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(normal_action)
        menu.addAction(compact_action)
        menu.addAction(companion_action)
        menu.addSeparator()
        menu.addAction(top_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self.tray = tray

    def reload_settings(self) -> None:
        if self.tray:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None
        self._create_tray()
        self.set_always_on_top(self.settings.always_on_top, persist=False)

    def apply_startup_state(self, *, autostart: bool = False) -> None:
        self.set_always_on_top(self.settings.always_on_top, persist=False)
        if self.settings.restore_window_state:
            self._restore_geometry()
        mode = self.settings.window_mode
        # 桌面陪伴会创建置顶的立绘和对话窗口。它们即使视觉上透明，仍会
        # 占据鼠标命中区域；把它作为上次退出后的自动恢复模式，会让用户
        # 误以为主界面失去响应。因此桌面陪伴只允许由用户在当前会话主动
        # 开启，重启后一律回到可操作的主窗口。
        if mode == "companion":
            self.settings.window_mode = "normal"
            mode = "normal"
        if self.mode_callback:
            self.mode_callback(mode)

    def _restore_geometry(self) -> None:
        data = self.settings.window_geometry
        try:
            width = max(620, int(data.get("width", 960)))
            height = max(480, int(data.get("height", 680)))
            x = int(data.get("x", self.window.x()))
            y = int(data.get("y", self.window.y()))
        except (TypeError, ValueError):
            return
        screen = QApplication.screenAt(self.window.frameGeometry().center()) or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            width = min(width, area.width())
            height = min(height, area.height())
            x = max(area.left(), min(x, area.right() - width + 1))
            y = max(area.top(), min(y, area.bottom() - height + 1))
        self.window.setGeometry(x, y, width, height)
        if bool(data.get("maximized", False)):
            self.window.showMaximized()

    def schedule_geometry_save(self) -> None:
        if self.settings.restore_window_state and not self.window.isMinimized():
            self._geometry_timer.start(350)

    def capture_geometry(self) -> None:
        if not self.settings.restore_window_state:
            return
        geometry = self.window.normalGeometry() if self.window.isMaximized() else self.window.geometry()
        self.settings.window_geometry = {
            "x": geometry.x(), "y": geometry.y(), "width": geometry.width(),
            "height": geometry.height(), "maximized": self.window.isMaximized(),
        }

    def set_mode(self, mode: str, *, persist: bool = True) -> None:
        mode = mode if mode in {"normal", "compact", "companion"} else "normal"
        if persist:
            self.settings.window_mode = mode
        if self.mode_callback:
            self.mode_callback(mode)
        if mode == "companion":
            if self.companion_callback:
                self.companion_callback(True)
            self.window.hide()
        else:
            if self.companion_callback:
                self.companion_callback(False)
            self.show_main()

    def set_always_on_top(self, enabled: bool, *, persist: bool = True) -> None:
        if persist:
            self.settings.always_on_top = bool(enabled)
        was_visible = self.window.isVisible()
        self.window.setWindowFlag(Qt.WindowStaysOnTopHint, bool(enabled))
        if was_visible:
            self.window.show()

    def show_main(self) -> None:
        if self.window.isMinimized():
            self.window.showNormal()
        else:
            self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def hide_to_tray(self, message: str = "莲心仍在后台陪伴，双击托盘图标可恢复。") -> bool:
        if not self.tray_available:
            return False
        self.capture_geometry()
        self.window.hide()
        if self.settings.desktop_notifications:
            self.tray.showMessage("莲心AI", message, QSystemTrayIcon.Information, 2500)
        return True

    def should_close_to_tray(self) -> bool:
        return self.settings.close_behavior == "tray" and self.tray_available

    def handle_minimize(self) -> bool:
        if self.settings.minimize_to_tray:
            return self.hide_to_tray("莲心已收进系统托盘，后台任务会继续运行。")
        return False

    def notify(self, title: str, message: str) -> bool:
        if self.tray_available and self.settings.desktop_notifications:
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 4000)
            return True
        return False

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.show_main()

    def _quit(self) -> None:
        if self.quit_callback:
            self.quit_callback()
        else:
            QApplication.quit()

    def shutdown(self) -> None:
        self.capture_geometry()
        if self.tray:
            self.tray.hide()
