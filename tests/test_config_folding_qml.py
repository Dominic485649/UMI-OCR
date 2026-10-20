"""不创建 QWindow 的配置折叠回归：真实 Configs.qml + PortableSettings。

默认显式加载仓库源码，只借用 data_root 的便携 PySide6；--packaged 仅使用给定包内的代码。
包模式优先使用其 ui.rcc/app.zip，否则使用包内磁盘文件，缺失时失败，绝不回退仓库源码。
"""

import argparse
import copy
import importlib.util
import json
import os
import sys
import tempfile
import time
import types
import zipimport
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_QML = ROOT / "UmiOCR-data" / "qt_res" / "qml" / "Configs" / "Configs.qml"
SOURCE_SETTINGS = ROOT / "UmiOCR-data" / "py_src" / "utils" / "portable_settings.py"


def run(data_root, packaged=False):
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("必须使用便携 Python 3.13。")
    if os.environ.get("QT_QPA_PLATFORM", "").lower() in {"offscreen", "minimal"}:
        raise RuntimeError("使用正常 Windows Qt 平台，不使用 offscreen/minimal。")
    sys.dont_write_bytecode = True
    data_root = data_root.resolve()
    packages = data_root / "site-packages"
    sys.path.insert(0, str(packages))
    dll_handles = [os.add_dll_directory(str(packages / "PySide6"))]
    from PySide6.QtCore import QFile, QObject, Property, QCoreApplication, QEvent, QResource, QUrl, Slot, qInstallMessageHandler
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtQuickControls2 import QQuickStyle
    from shiboken6 import isValid

    mode = "packaged" if packaged else "source"
    registered_rcc = None
    if packaged:
        # 与实际入口一致：有 ui.rcc 就测该载荷，不退回磁盘副本，更不借用仓库文件。
        rcc = (data_root / "ui.rcc").resolve()
        if rcc.is_file():
            assert rcc.is_relative_to(data_root), "ui.rcc 不能跳出指定包。"
            assert QResource.registerResource(str(rcc)), f"无法注册包内资源：{rcc}"
            registered_rcc = rcc
            qml_origin = "qrc:/qt_res/qml/Configs/Configs.qml"
            qml_payload = rcc
            assert QFile.exists(":/qt_res/qml/Configs/Configs.qml"), "包内 ui.rcc 缺少 Configs.qml。"
            qml_url = QUrl(qml_origin)
        else:
            qml_payload = (data_root / "qt_res" / "qml" / "Configs" / "Configs.qml").resolve()
            assert qml_payload.is_relative_to(data_root), "QML 路径不能跳出指定包。"
            assert qml_payload.is_file(), f"包内缺少 Configs.qml，不回退源码：{qml_payload}"
            qml_origin = str(qml_payload)
            qml_url = QUrl.fromLocalFile(qml_origin)

        archive = (data_root / "app.zip").resolve()
        if archive.is_file():
            assert archive.is_relative_to(data_root), "app.zip 不能跳出指定包。"
            # 只执行该归档中的模块，不修改 sys.path 去寻找其它 py_src 副本。
            loader = zipimport.zipimporter(str(archive) + "/py_src/utils/")
            settings_module = types.ModuleType("packaged_portable_settings_fold_test")
            settings_module.__file__ = loader.get_filename("portable_settings")
            settings_module.__loader__ = loader
            exec(loader.get_code("portable_settings"), settings_module.__dict__)
        else:
            settings_path = (data_root / "py_src" / "utils" / "portable_settings.py").resolve()
            assert settings_path.is_relative_to(data_root), "PortableSettings 路径不能跳出指定包。"
            assert settings_path.is_file(), f"包内缺少 PortableSettings，不回退源码：{settings_path}"
            spec = importlib.util.spec_from_file_location("packaged_portable_settings_fold_test", settings_path)
            settings_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(settings_module)
        settings_origin = Path(settings_module.__file__).resolve()
        assert settings_origin.is_relative_to(data_root), f"误加载了包外 PortableSettings：{settings_origin}"
        assert qml_payload.is_relative_to(data_root), f"误加载了包外 QML 载荷：{qml_payload}"
    else:
        qml_payload = SOURCE_QML.resolve()
        qml_origin = str(qml_payload)
        qml_url = QUrl.fromLocalFile(qml_origin)
        spec = importlib.util.spec_from_file_location("source_portable_settings_fold_test", SOURCE_SETTINGS)
        settings_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(settings_module)
        settings_origin = Path(settings_module.__file__).resolve()
        assert settings_origin == SOURCE_SETTINGS.resolve()
        assert qml_payload == SOURCE_QML.resolve()
    PortableSettings = settings_module.PortableSettings

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication.instance() or QGuiApplication(["config-folding-item-test"])
    # 这个测试进程不构造/显示任何窗口；每个阶段都检查，避免干扰其它进程的原生鼠标验收。
    assert not app.allWindows(), "测试开始时不应有 QWindow。"
    messages = []
    previous_handler = qInstallMessageHandler(lambda _kind, _context, text: messages.append(text))

    class BusStub(QObject):
        @Slot(str, "QVariant", str, str)
        def subscribeGroup(self, _title, _item, _method, _group):
            pass

        @Slot(str)
        def unsubscribeGroup(self, _group):
            pass

    class PopupStub(QObject):
        @Slot(str, str, str)
        def message(self, _title, _text, _kind):
            raise AssertionError("折叠测试不应显示任何消息窗口。")

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

    qml_app = AppStub()
    engine = QQmlEngine()
    engine.addImportPath(str(packages / "PySide6" / "qml"))
    context = engine.rootContext()
    context.setContextProperty("qmlapp", qml_app)
    context.setContextProperty("theme", {
        **{name: QColor(value) for name, value in {
            "bgColor": "#ffffff", "textColor": "#111111", "subTextColor": "#555555", "noColor": "#bb3322",
            "yesColor": "#228844", "specialBgColor": "#eeeeee", "specialTextColor": "#1166cc",
            "coverColor1": "#11000000", "coverColor2": "#22000000", "coverColor3": "#33000000", "coverColor4": "#55000000"
        }.items()}, "fontFamily": "Microsoft YaHei", "dataFontFamily": "Microsoft YaHei"})
    context.setContextProperty("size_", {"scale": 1, "line": 20, "smallLine": 16, "largeLine": 24,
        "text": 14, "smallText": 12, "largeText": 18, "spacing": 8, "smallSpacing": 4, "btnRadius": 4, "panelRadius": 6})
    # 故意不注入 uiSettings：生产入口也只有 UmiSettings，旧全局桩会掩盖本次错误。
    component = QQmlComponent(engine, qml_url)
    assert component.url() == qml_url, "QML 组件 URL 与指定载荷不一致。"
    roots = []

    def wait(predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            app.processEvents()
            assert not app.allWindows(), "配置 Item 回归不能创建 QWindow。"
            if predicate():
                return
        raise AssertionError("配置组件未就绪。")

    def checkpoint():
        app.processEvents()
        assert not app.allWindows(), "配置 Item 回归不能创建 QWindow。"
        errors = [message for message in messages if any(marker in message for marker in (
            "ReferenceError:", "TypeError:", "SyntaxError:", "Unable to assign", "Cannot assign", "Binding loop"))]
        assert not errors, (f"模式={mode}；QML载荷={qml_payload}；PortableSettings={settings_origin}；"
                            "QWindow 数量=0；QML 错误：\n" + "\n".join(errors[:8]))

    def evaluate(code):
        result = engine.evaluate(code)
        assert not result.isError(), result.toString()
        return result

    def fold(name):
        return evaluate(f'testedConfigs.compList.find(function(item){{return item.key==="outer.{name}"}}).fold').toBool()

    def click_fold(name):
        group = evaluate(f'testedConfigs.compList.find(function(item){{return item.key==="outer.{name}"}})').toQObject()
        buttons = [child for child in group.children()
                   if child.metaObject().indexOfProperty("text_") >= 0 and child.metaObject().indexOfProperty("bgPressColor_") >= 0]
        assert len(buttons) == 1
        engine.globalObject().setProperty("testedFoldButton", engine.newQObject(buttons[0]))
        evaluate("testedFoldButton.clicked()")
        checkpoint()

    definition = {"outer": {"type": "group", "title": "配置组"}}
    for name, default, enabled in (
        ("defaultClosed", True, True), ("defaultOpen", False, True),
        ("savedClosed", False, True), ("savedOpen", True, True),
        ("legacyClosed", False, True), ("legacyOpen", True, True), ("fixedClosed", True, False),
    ):
        definition["outer"][name] = {"type": "group", "title": name, "enabledFold": enabled, "fold": default}

    try:
        wait(lambda: not component.isLoading())
        with tempfile.TemporaryDirectory(prefix="umi-config-fold-qml-") as directory:
            path = str(Path(directory) / ".settings")
            settings = PortableSettings(path)
            for name, value in {"savedClosed": True, "savedOpen": False, "legacyClosed": "true",
                                "legacyOpen": "false", "fixedClosed": False}.items():
                settings.setValue("UI", f"outer.{name}.fold", value)
            settings.setValue("UI", "unrelated", "keep")
            settings.setValue("ConfigFoldRegression", "outer.savedClosed.fold", "business-sentinel")
            settings.sync()
            context.setContextProperty("UmiSettings", settings)

            def create_configs():
                obj = component.createWithInitialProperties({"category_": "ConfigFoldRegression", "width": 720,
                    "height": 400, "configDict": copy.deepcopy(definition)})
                assert obj is not None, component.errorString()
                assert isinstance(obj, QQuickItem), "必须只创建配置 Item。"
                roots.append(obj)
                engine.globalObject().setProperty("testedConfigs", engine.newQObject(obj))
                checkpoint()
                return obj

            configs = create_configs()
            expected = {"defaultClosed": True, "defaultOpen": False, "savedClosed": True, "savedOpen": False,
                        "legacyClosed": True, "legacyOpen": False, "fixedClosed": True}
            assert {name: fold(name) for name in expected} == expected
            for name in ("savedClosed", "savedOpen", "legacyClosed"):
                before = fold(name)
                click_fold(name)
                assert fold(name) is (not before)
                assert settings.value("UI", f"outer.{name}.fold", None) is (not before)
                expected[name] = not before
            assert settings.value("UI", "unrelated", None) == "keep"
            assert settings.value("ConfigFoldRegression", "outer.savedClosed.fold", None) == "business-sentinel"
            settings.sync()

            # 新设置对象和新组件重建，验证持久化记录仍在 UI 类别，且布尔/旧字符串兼容。
            configs.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            restored = PortableSettings(path)
            context.setContextProperty("UmiSettings", restored)
            create_configs()
            assert {name: fold(name) for name in expected} == expected
            assert restored.value("UI", "unrelated", None) == "keep"
            assert restored.value("ConfigFoldRegression", "outer.savedClosed.fold", None) == "business-sentinel"
            checkpoint()
            for obj in roots:
                if isValid(obj):
                    obj.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            settings.sync()
            restored.sync()
    finally:
        for obj in roots:
            if isValid(obj):
                obj.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not app.allWindows(), "测试结束时不应有 QWindow。"
        qInstallMessageHandler(previous_handler)
        if registered_rcc:
            QResource.unregisterResource(str(registered_rcc))
        del dll_handles

    return {"mode": mode, "data_root": str(data_root), "python": sys.version.split()[0],
            "source_qml": qml_origin, "qml_url": qml_url.toString(), "qml_payload": str(qml_payload),
            "source_settings": str(settings_origin), "qwindow_count": 0,
            "passed": ["缺省折叠状态", "UI 类别布尔与旧字符串读取", "实际折叠按钮写回原 UI key",
            "新 PortableSettings/配置 Item 重建保留折叠状态", "业务类别与无关 UI 记录不变", "无 QML ReferenceError 或窗口"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path, help="便携 PySide6 所在目录；--packaged 时也只加载此目录内的代码")
    parser.add_argument("--packaged", action="store_true", help="仅测试 data_root 内的 QML/PortableSettings，缺失时失败，不回退仓库源码")
    args = parser.parse_args()
    print(json.dumps(run(args.data_root, packaged=args.packaged), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
