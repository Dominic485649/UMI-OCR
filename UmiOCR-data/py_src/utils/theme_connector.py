# =========================================
# =============== 主题连接器 ===============
# =========================================

from PySide6.QtCore import QObject, Property, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication

from umi_log import logger

ThemePath = "themes.json"


class ThemeConnector(QObject):
    systemDarkChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._system_dark = self._read_system_dark()
        style_hints = QGuiApplication.styleHints()
        style_hints.colorSchemeChanged.connect(self._on_color_scheme_changed)

    @staticmethod
    def _read_system_dark():
        return (
            QGuiApplication.styleHints().colorScheme()
            == Qt.ColorScheme.Dark
        )

    def _on_color_scheme_changed(self, color_scheme):
        system_dark = color_scheme == Qt.ColorScheme.Dark
        if system_dark != self._system_dark:
            self._system_dark = system_dark
            self.systemDarkChanged.emit()

    @Property(bool, notify=systemDarkChanged)
    def systemDark(self):
        return self._system_dark

    # 读取主题
    @Slot(result=str)
    def loadThemeStr(self):
        try:
            with open(ThemePath, "r", encoding="utf-8") as f:
                r = f.read()
                return r
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("读取主题文件失败。", exc_info=True)
        return ""

    # 保存主题
    @Slot(str)
    def saveThemeStr(self, tstr):
        try:
            with open(ThemePath, "w", encoding="utf-8") as f:
                f.write(tstr)
        except Exception:
            logger.warning("写入主题文件失败。", exc_info=True)
