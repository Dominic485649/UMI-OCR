# =========================================
# =============== 主题连接器 ===============
# =========================================

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, Property, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QPlatformSurfaceEvent

from umi_log import logger
from .runtime_i18n import tr

ThemePath = "themes.json"


class ThemeConnector(QObject):
    systemDarkChanged = Signal()
    nativeThemeFailed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._system_dark = self._read_system_dark()
        self._window = None
        self._window_dark = False
        self._last_native_error = ""
        self._native_refresh = QTimer(self)
        self._native_refresh.setSingleShot(True)
        self._native_refresh.timeout.connect(self._apply_window_theme)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_color_scheme_changed)

    @staticmethod
    def _read_system_dark():
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark

    def _on_color_scheme_changed(self, color_scheme):
        system_dark = color_scheme == Qt.ColorScheme.Dark
        if system_dark != self._system_dark:
            self._system_dark = system_dark
            self.systemDarkChanged.emit()

    @Property(bool, notify=systemDarkChanged)
    def systemDark(self):
        return self._system_dark

    @Slot(QObject, bool)
    def syncWindowTheme(self, window, dark):
        """使用软件已生效的颜色，不从系统主题推断标题栏主题。"""
        if window is not self._window:
            if self._window is not None:
                self._window.removeEventFilter(self)
            self._window = window
            if window is not None:
                window.installEventFilter(self)
        self._window_dark = dark
        if window is not None and sys.platform == "win32":
            self._native_refresh.start(0)

    def eventFilter(self, watched, event):
        if watched is self._window and sys.platform == "win32":
            kind = event.type()
            if kind == QEvent.Type.PlatformSurface:
                if event.surfaceEventType() == QPlatformSurfaceEvent.SurfaceEventType.SurfaceCreated:
                    self._native_refresh.start(0)
                else:
                    self._native_refresh.stop()
            elif kind in (QEvent.Type.Show, QEvent.Type.WinIdChange):
                # 置顶改变 flags 后，原生句柄可能重建。合并到下一轮事件再同步。
                self._native_refresh.start(0)
        return super().eventFilter(watched, event)

    @staticmethod
    def _set_native_dark(hwnd, dark):
        dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        setter = dwm.DwmSetWindowAttribute
        setter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        setter.restype = ctypes.c_long
        enabled = wintypes.BOOL(bool(dark))
        result = setter(hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled))
        if result < 0:
            # 较早 Windows 10 使用属性 19；失败仍明确报告，不修改系统设置。
            result = setter(hwnd, 19, ctypes.byref(enabled), ctypes.sizeof(enabled))
        if result < 0:
            raise OSError(f"DwmSetWindowAttribute HRESULT=0x{result & 0xffffffff:08X}")

    def _apply_window_theme(self):
        if sys.platform != "win32" or self._window is None:
            return
        try:
            self._set_native_dark(int(self._window.winId()), self._window_dark)
            self._last_native_error = ""
        except Exception as exc:
            message = tr("同步 Windows 标题栏主题失败：{error}", error=exc)
            # 相同故障只提示一次，避免窗口显示事件导致重复通知。
            if message != self._last_native_error:
                self._last_native_error = message
                logger.warning(message)
                self.nativeThemeFailed.emit(message)

    # 读取主题
    @Slot(result=str)
    def loadThemeStr(self):
        try:
            with open(ThemePath, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning(tr("读取主题文件失败。"), exc_info=True)
        return ""

    # 保存主题
    @Slot(str)
    def saveThemeStr(self, tstr):
        try:
            with open(ThemePath, "w", encoding="utf-8") as f:
                f.write(tstr)
        except Exception:
            logger.warning("写入主题文件失败。", exc_info=True)
