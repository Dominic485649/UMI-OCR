from PySide6.QtCore import QObject, QSettings, Slot
from PySide6.QtQml import QJSValue


def _to_variant(value):
    if isinstance(value, QJSValue):
        if value.isUndefined():
            return None
        return _to_variant(value.toVariant())
    if isinstance(value, dict):
        return {key: _to_variant(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_variant(item) for item in value]
    return value


class PortableSettings(QObject):
    def __init__(self, file_name, parent=None):
        super().__init__(parent)
        self._settings = QSettings(file_name, QSettings.Format.IniFormat)
        self._settings.setFallbacksEnabled(False)

    @staticmethod
    def _key(category, key):
        return f"{category}/{key}" if category else key

    @Slot(str, str, "QVariant", result="QVariant")
    def value(self, category, key, default=None):
        value = self._settings.value(self._key(category, key), _to_variant(default))
        if isinstance(value, QJSValue):
            value = _to_variant(value)
            self._settings.setValue(self._key(category, key), value)
        return value

    @Slot(str, str, result=bool)
    def contains(self, category, key):
        return self._settings.contains(self._key(category, key))

    @Slot(str, str, "QVariant")
    def setValue(self, category, key, value):
        self._settings.setValue(self._key(category, key), _to_variant(value))

    @Slot(str, str)
    def remove(self, category, key):
        self._settings.remove(self._key(category, key))

    @Slot()
    def sync(self):
        self._settings.sync()
