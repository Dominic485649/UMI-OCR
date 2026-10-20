"""Windowless enum regression using real Configs.qml and portable Qt.

Choose --source or --packaged explicitly. Package mode prefers its actual ui.rcc,
otherwise loads only its disk QML; missing payloads/dependencies never fall back
to repository code. Settings and warm-up hooks are memory-only. This is not full
release acceptance or a real mouse/keyboard interaction test.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_QML = ROOT / "UmiOCR-data" / "qt_res" / "qml" / "Configs" / "Configs.qml"
CATEGORY = "ConfigEnumRegression"
KEY = "ocr.lifecycle.warmupMode"


def _value(value):
    return value.toVariant() if hasattr(value, "toVariant") else value


def run(data_root, *, packaged):
    if sys.platform != "win32" or sys.version_info[:2] != (3, 13):
        raise RuntimeError("Use the Windows portable Python 3.13 runtime.")
    if os.environ.get("QT_QPA_PLATFORM", "").lower() in {"offscreen", "minimal"}:
        raise RuntimeError("Use the normal Windows Qt platform, without creating a window.")
    sys.dont_write_bytecode = True
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    data_root = data_root.resolve()
    source_root = data_root if packaged else (ROOT / "UmiOCR-data").resolve()
    mode = "packaged" if packaged else "source"
    packages = data_root / "site-packages"
    sys.path.insert(0, str(packages))
    dll_handles = [os.add_dll_directory(str(packages / "PySide6"))]
    from PySide6.QtCore import QFile, QObject, Property, QCoreApplication, QEvent, QResource, QtMsgType, QUrl, Slot, qInstallMessageHandler
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtQuickControls2 import QQuickStyle
    from shiboken6 import isValid

    class MemorySettings(QObject):
        def __init__(self):
            super().__init__()
            self.values = {(CATEGORY, KEY): "lazy"}
            self.writes = []

        @Slot(str, str, result=bool)
        def contains(self, category, key):
            return (category, key) in self.values

        @Slot(str, str, "QVariant", result="QVariant")
        def value(self, category, key, default):
            return self.values.get((category, key), _value(default))

        @Slot(str, str, "QVariant")
        def setValue(self, category, key, value):
            value = _value(value)
            self.values[category, key] = value
            self.writes.append((category, key, value))

        @Slot(str, str)
        def remove(self, category, key):
            self.values.pop((category, key), None)

        @Slot()
        def sync(self):
            pass

    class ChangeProbe(QObject):
        def __init__(self):
            super().__init__()
            self.changes = []
            self.warmup_requests = []

        @Slot(str, bool)
        def changed(self, value, has_old_value):
            self.changes.append((value, has_old_value))
            # Record the dangerous transition without importing/starting a backend.
            if has_old_value and value == "delayed":
                self.warmup_requests.append(value)

    class BusStub(QObject):
        @Slot(str, "QVariant", str, str)
        def subscribeGroup(self, _title, _item, _method, _group):
            pass

        @Slot(str)
        def unsubscribeGroup(self, _group):
            pass

    class PopupStub(QObject):
        def __init__(self, parent):
            super().__init__(parent)
            self.messages = []

        @Slot(str, str, str)
        def message(self, title, text, kind):
            self.messages.append((title, text, kind))

    class AppStub(QObject):
        def __init__(self):
            super().__init__()
            self.bus = BusStub(self)
            self.popup_stub = PopupStub(self)

        @Property(bool, constant=True)
        def enabledEffect(self):
            return False

        @Property(QObject, constant=True)
        def pubSub(self):
            return self.bus

        @Property(QObject, constant=True)
        def popup(self):
            return self.popup_stub

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication.instance() or QGuiApplication(["config-enum-component-test"])
    assert not app.allWindows(), "This test must not create a QWindow."
    messages = []
    previous_handler = qInstallMessageHandler(lambda kind, _context, text: messages.append((kind, text)))
    settings, probe, qml_app = MemorySettings(), ChangeProbe(), AppStub()
    engine = QQmlEngine()
    engine.addImportPath(str(packages / "PySide6" / "qml"))
    context = engine.rootContext()
    context.setContextProperty("UmiSettings", settings)
    engine.globalObject().setProperty("changeProbe", engine.newQObject(probe))
    context.setContextProperty("qmlapp", qml_app)
    context.setContextProperty("theme", {
        **{name: QColor(value) for name, value in {
            "bgColor": "#ffffff", "textColor": "#111111", "subTextColor": "#555555", "noColor": "#bb3322",
            "yesColor": "#228844", "specialBgColor": "#eeeeee", "specialTextColor": "#1166cc",
            "coverColor1": "#11000000", "coverColor2": "#22000000", "coverColor3": "#33000000", "coverColor4": "#55000000",
        }.items()}, "fontFamily": "Microsoft YaHei", "dataFontFamily": "Microsoft YaHei",
    })
    context.setContextProperty("size_", {"scale": 1, "line": 20, "smallLine": 16, "largeLine": 24,
        "text": 14, "smallText": 12, "largeText": 18, "spacing": 8, "smallSpacing": 4, "btnRadius": 4, "panelRadius": 6})
    qml_url = None
    registered_rcc = None
    component = None
    configs = None
    commits = []
    passed = []
    provenance = {"mode": mode, "source_root": str(source_root)}
    app_qml_sources = set()

    def verify_origins():
        if configs is None:
            return
        actual_url = QQmlEngine.contextForObject(configs).baseUrl()
        assert actual_url == qml_url, ("Unexpected component context URL", actual_url.toString(), provenance)
        provenance["context_base_url"] = actual_url.toString()
        for obj in [configs, *configs.findChildren(QObject)]:
            obj_context = QQmlEngine.contextForObject(obj)
            if obj_context is None:
                continue
            origin = obj_context.baseUrl()
            if origin.isLocalFile() and "/qt_res/qml/" in origin.path().replace("\\", "/").lower():
                actual_file = Path(origin.toLocalFile()).resolve()
                assert actual_file.is_relative_to(source_root), ("Application QML escaped source_root", str(actual_file), provenance)
                assert registered_rcc is None, ("Resource mode loaded disk application QML", origin.toString(), provenance)
                app_qml_sources.add(origin.toString())
            elif origin.scheme() == "qrc" and origin.path().startswith("/qt_res/qml/"):
                assert registered_rcc is not None, ("Unselected application resource was loaded", origin.toString(), provenance)
                app_qml_sources.add(origin.toString())
        assert actual_url.toString() in app_qml_sources, provenance
        provenance["app_qml_sources"] = sorted(app_qml_sources)

    def checkpoint(label):
        app.processEvents()
        assert not app.allWindows(), f"{label}: a QWindow was created."
        errors = [text for kind, text in messages if kind in (
            QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)]
        assert not errors, (label, provenance, errors[:8])
        assert not qml_app.popup_stub.messages, qml_app.popup_stub.messages
        backend_modules = [name for name in sys.modules if name == "py_src" or name.startswith("py_src.")
                           or name.split(".")[0] in {"paddle", "paddlex", "paddleocr", "onnxruntime"}]
        assert not backend_modules, f"Backend modules must not be imported: {backend_modules[:8]}"
        verify_origins()

    def evaluate(code):
        value = engine.evaluate(code)
        assert not value.isError(), (value.toString(), provenance)
        return value

    def current_value():
        return evaluate(f"testedConfigs.getValue({json.dumps(KEY)})").toString()

    def expect_commits(values, label):
        checkpoint(label)
        assert settings.writes == [(CATEGORY, KEY, value) for value in values], (label, provenance, settings.writes)
        assert commits == [(KEY, value) for value in values], (label, provenance, commits)
        assert probe.changes == [("lazy", False)] + [(value, True) for value in values], (label, provenance, probe.changes)
        assert current_value() == (values[-1] if values else "lazy"), (label, provenance)
        assert settings.values == {(CATEGORY, KEY): current_value()}, (label, provenance)

    def bind_combo():
        item = evaluate(f"testedConfigs.compDict[{json.dumps(KEY)}]").toQObject()
        assert isinstance(item, QQuickItem), "The actual Configs enum item must be instantiated."
        combos = [child for child in item.children()
                  if child.metaObject().indexOfSignal("activated(int)") >= 0
                  and child.metaObject().indexOfProperty("currentIndex") >= 0]
        assert len(combos) == 1, "Expected the real Qt Quick Controls ComboBox."
        engine.globalObject().setProperty("testedCombo", engine.newQObject(combos[0]))

    try:
        if packaged:
            rcc = (data_root / "ui.rcc").resolve()
            assert rcc.is_relative_to(data_root), f"ui.rcc escaped the package: {rcc}"
            if rcc.is_file():
                assert not QFile.exists(":/qt_res/qml/Configs/Configs.qml"), "An existing application resource makes provenance ambiguous."
                assert QResource.registerResource(str(rcc)), f"Cannot register packaged ui.rcc: {rcc}"
                registered_rcc = rcc
                qml_payload = rcc
                qml_url = QUrl("qrc:/qt_res/qml/Configs/Configs.qml")
                for name in ("Configs.qml", "ConfigItemComp.qml", "Settings_.qml"):
                    assert QFile.exists(f":/qt_res/qml/Configs/{name}"), f"Packaged ui.rcc lacks {name}; no disk/source fallback: {rcc}"
                provenance["qml_origin"] = "packaged-resource"
            else:
                qml_payload = (data_root / "qt_res" / "qml" / "Configs" / "Configs.qml").resolve()
                assert qml_payload.is_relative_to(data_root), f"Configs.qml escaped the package: {qml_payload}"
                for name in ("Configs.qml", "ConfigItemComp.qml", "Settings_.qml"):
                    dependency = (qml_payload.parent / name).resolve()
                    assert dependency.is_relative_to(data_root) and dependency.is_file(), (
                        f"Packaged {name} is missing or outside data_root; no source fallback: {dependency}")
                qml_url = QUrl.fromLocalFile(str(qml_payload))
                provenance["qml_origin"] = "packaged-files"
        else:
            qml_payload = SOURCE_QML.resolve()
            assert qml_payload.is_file() and qml_payload.is_relative_to(source_root), str(qml_payload)
            qml_url = QUrl.fromLocalFile(str(qml_payload))
            provenance["qml_origin"] = "repository-source"
        provenance.update(qml_payload=str(qml_payload), qml_url=qml_url.toString())
        component = QQmlComponent(engine, qml_url)
        deadline = time.monotonic() + 5
        while component.isLoading():
            assert time.monotonic() < deadline, ("QML loading timed out", provenance)
            checkpoint("load selected component")
        assert component.url() == qml_url and component.isReady(), (provenance, component.errorString())
        configs = component.createWithInitialProperties({"category_": CATEGORY, "autoLoad": False,
            "lazyPanel": True, "width": 720, "height": 320})
        assert isinstance(configs, QQuickItem), (provenance, component.errorString())
        verify_origins()
        configs.valueCommitted.connect(lambda key, value: commits.append((key, _value(value))))
        engine.globalObject().setProperty("testedConfigs", engine.newQObject(configs))
        definition = {"ocr": {"title": "OCR", "type": "group", "lifecycle": {
            "title": "Lifecycle", "type": "group", "warmupMode": {"title": "Warm-up", "default": "lazy",
                "optionsList": [["delayed", "Delayed"], ["lazy", "Lazy"]]},
        }}}
        evaluate("testedConfigs.configDict = " + json.dumps(definition))
        evaluate("testedConfigs.configDict.ocr.lifecycle.warmupMode.onChanged = function(value, old) {"
                 "changeProbe.changed(value, old !== undefined); }")
        evaluate("testedConfigs.reload()")
        expect_commits([], "load saved lazy policy")
        evaluate("testedConfigs.initPanelComponent()")
        expect_commits([], "construct enum without saving or committing")
        bind_combo()
        assert evaluate("testedCombo.currentIndex").toInt() == 1
        assert not probe.warmup_requests, "Constructing controls must not request warm-up."
        passed.append("control construction preserves lazy without saves, commits, or warm-up requests")

        # These are real ComboBox model/index mutations, not a substitute enum stub.
        for code in ("testedCombo.model = []", "testedCombo.model = ['New delayed', 'New lazy']",
                     "testedCombo.currentIndex = 0", "testedCombo.currentIndex = 1",
                     f"testedConfigs.compDict[{json.dumps(KEY)}].updateUI()"):
            evaluate(code)
            expect_commits([], code)
        assert evaluate("testedCombo.currentIndex").toInt() == 1
        evaluate("testedConfigs.initPanelComponent()")
        expect_commits([], "rebuild enum panel")
        bind_combo()
        assert evaluate("testedCombo.currentIndex").toInt() == 1
        assert not probe.warmup_requests
        passed.append("model replacement, index changes, updateUI, and panel rebuild are presentation-only")

        values = []
        for value, index in (("delayed", 0), ("lazy", 1)):
            evaluate(f"testedConfigs.setValue({json.dumps(KEY)}, {json.dumps(value)}, true)")
            values.append(value)
            expect_commits(values, "programmatic setValue with UI refresh")
            assert evaluate("testedCombo.currentIndex").toInt() == index
        passed.append("setValue(key, value, true) persists and commits once while updating selection")

        # Emit the real activated signal without OS input, opening the popup, or creating a window.
        for value, index in (("delayed", 0), ("lazy", 1)):
            evaluate(f"testedCombo.currentIndex = {index}")
            expect_commits(values, "index change before activation")
            evaluate(f"testedCombo.activated({index})")
            values.append(value)
            expect_commits(values, "real ComboBox activated signal")
            evaluate(f"testedCombo.activated({index})")
            expect_commits(values, "reactivating the same value is a no-op")
        passed.append("actual activated signal commits once; same-value activation does not commit")

        evaluate("testedConfigs.configDict.ocr.lifecycle.warmupMode.onChanged = function(value, old) {"
                 "if (value === 'delayed') return true; changeProbe.changed(value, old !== undefined); }")
        evaluate("testedCombo.currentIndex = 0; testedCombo.activated(0)")
        expect_commits(values, "vetoed activation restores UI without recursive commits")
        assert evaluate("testedCombo.currentIndex").toInt() == 1
        passed.append("onChanged veto restores selection without saving or recursive commits")
        checkpoint("finish")
    finally:
        if configs is not None and isValid(configs):
            configs.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        if component is not None and isValid(component):
            component.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not app.allWindows(), "A component test must finish without any QWindow."
        qInstallMessageHandler(previous_handler)
        if registered_rcc is not None:
            QResource.unregisterResource(str(registered_rcc))
        del dll_handles

    return {**provenance, "scope": "windowless-enum-component-only", "full_release_acceptance": False,
            "python": sys.version.split()[0], "portable_qt_root": str(data_root),
            "settings": "memory-only", "qwindow_count": 0, "backend_imports": [],
            "initial_warmup_requests": [], "passed": passed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path, help="Portable UmiOCR-data; package mode also loads its QML only")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--source", action="store_true", help="Load repository source QML explicitly")
    modes.add_argument("--packaged", action="store_true", help="Load data_root ui.rcc/disk QML only; never fall back to source")
    args = parser.parse_args()
    print(json.dumps(run(args.data_root, packaged=args.packaged), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
