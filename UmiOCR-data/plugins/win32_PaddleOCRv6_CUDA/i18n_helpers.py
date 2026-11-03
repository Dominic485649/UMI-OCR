"""宿主与独立 worker 共用的轻量文案翻译，不导入 Qt。"""
import csv
import os
from pathlib import Path

_CACHE = {}


def language():
    try:
        from plugin_i18n import LangCode
        return LangCode or "zh_CN"
    except ImportError:
        return os.environ.get("UMI_PLUGIN_LANGUAGE", "zh_CN")


def tr(message, **values):
    code = language()
    if code not in _CACHE:
        translations = {}
        path = Path(__file__).with_name("i18n.csv")
        if path.is_file():
            with path.open(encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    if row.get("zh_CN") and row.get(code):
                        translations[row["zh_CN"]] = row[code]
        _CACHE[code] = translations
    return _CACHE[code].get(message, message).format(**values) if values else _CACHE[code].get(message, message)
