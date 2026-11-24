"""Lazy, Qt-free translations for host Python runtime messages.

The language is read on every call, so changing language does not require
reloading mission/server modules. Only the immutable catalogue is cached.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from importlib import import_module
from pathlib import Path
import sys

def _catalogue_path(module_file):
    path = Path(module_file).resolve()
    # zipimport uses a virtual __file__ inside app.zip. The catalogue is a
    # real sibling of the archive, not an entry inside that virtual path.
    for parent in path.parents:
        if parent.name.casefold() == "app.zip":
            return parent.parent / "i18n" / "runtime.csv"
    return path.parents[2] / "i18n" / "runtime.csv"


_CATALOGUE_PATH = _catalogue_path(__file__)


def language():
    """Use the host's current language without importing Qt or changing state."""
    for name in ("plugin_i18n", "py_src.imports.plugin_i18n"):
        module = sys.modules.get(name)
        if module is not None:
            return getattr(module, "LangCode", "") or "zh_CN"
    # In the application this module is already loaded. Import it lazily only
    # when called in an independently loaded host module.
    for name in ("plugin_i18n", "py_src.imports.plugin_i18n"):
        try:
            module = import_module(name)
        except ImportError:
            continue
        return getattr(module, "LangCode", "") or "zh_CN"
    return "zh_CN"


@lru_cache(maxsize=1)
def _catalogue():
    try:
        with _CATALOGUE_PATH.open(encoding="utf-8-sig", newline="") as stream:
            return {row["zh_CN"]: row for row in csv.DictReader(stream) if row.get("zh_CN")}
    except FileNotFoundError:
        # A broken/incomplete installation must not crash the UI while trying
        # to report another error. Independent coverage tests still fail if
        # this file is absent, so graceful fallback is never a coverage PASS.
        return {}


def tr(message, **values):
    """Translate a stable source template, then interpolate named values.

    Unsupported languages or unknown templates keep the source, as in Qt.
    Coverage tests reject missing/empty entries in every supported language;
    source fallback must never be counted as translation coverage.
    """
    code = language()
    template = message
    if code != "zh_CN":
        template = _catalogue().get(message, {}).get(code) or message
    return template.format(**values)
