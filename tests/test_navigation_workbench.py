"""真实 QML 工作台定向回归；内存状态、无窗口、无模型、无用户配置。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]


def run(data, source):
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    packages = data / "site-packages"
    sys.path[:0] = [str(packages), str(data / "dependencies.zip")]
    handle = os.add_dll_directory(str(packages / "PySide6"))
    from PySide6.QtCore import QObject, QCoreApplication, QEvent, QPointF, QTimer, QUrl, QtMsgType, qInstallMessageHandler
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression, qmlRegisterType
    from PySide6.QtQuickControls2 import QQuickStyle

    class PageConnector(QObject):
        """本测试只枚举内置页面；不允许创建 Python 页面控制器。"""

    qmlRegisterType(PageConnector, "TagPageConnector", 1, 0, "TagPageConnector")
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(["navigation-workbench-windowless"])
    assert not app.allWindows()
    engine = QQmlEngine()
    engine.addImportPath(str(packages / "PySide6/qml"))
    context = engine.rootContext()
    qml = source / "qt_res/qml"
    about = json.loads((source / "about.json").read_text("utf-8-sig"))
    about["version"]["string"] = ".".join(str(about["version"][key]) for key in ("major", "minor", "patch"))
    context.setContextProperty("UmiAbout", about)
    messages, cases, failures = [], [], []
    previous = qInstallMessageHandler(lambda kind, _context, text: messages.append((kind, text)))
    theme = {**{name: QColor(value) for name, value in {
        "bgColor": "#ffffff", "textColor": "#1f2328", "subTextColor": "#59636e", "noColor": "#d1242f",
        "yesColor": "#16833a", "specialBgColor": "#f0f2f4", "specialTextColor": "#1f6feb",
        "coverColor1": "#0d1f2328", "coverColor2": "#171f2328", "coverColor3": "#291f2328", "coverColor4": "#421f2328",
    }.items()}, "fontFamily": "Microsoft YaHei", "dataFontFamily": "Microsoft YaHei"}
    context.setContextProperty("theme", theme)

    def sizes(scale):
        return {"scale": scale, "line": 16 * scale, "smallLine": 13 * scale, "largeLine": 20 * scale,
                "text": 16 * scale, "smallText": 13 * scale, "largeText": 20 * scale,
                "spacing": 7 * scale, "smallSpacing": 4 * scale,
                "btnRadius": 6 * scale, "panelRadius": 10.2 * scale, "baseRadius": 6 * scale}

    context.setContextProperty("size_", sizes(1))
    fixture_component = QQmlComponent(engine)
    fixture_component.setData(('import QtQuick 2.15\nimport "' + QUrl.fromLocalFile(str(qml / "TabPages")).toString() + '''"
Item {
    id: fixture
    width: 1040; height: 760
    property bool enabledEffect: false
    property bool showDocumentCard: false
    property alias tab: tabs
    property alias globalConfigs: shared
    property var operations: []
    Item {
        id: shared
        property var pluginStates: []
        function pluginStateText(state) { return state === "disabled" ? "已禁用" : state }
    }
    Item {
        id: tabs
        property var infoList: registry.infoList.concat(fixture.showDocumentCard
            ? [{key: "StructuredDocument", title: "文档解析", intro: "还原版面、表格和公式并导出 Markdown。"}] : [])
        function getTabPageIndex(page) { return 0 }
        function changeTabPage(index, infoIndex) { fixture.operations.push(["task", index, infoIndex]) }
        function openTabPageByKey(key) { fixture.operations.push(["open", key]); return settingsTarget }
    }
    Item {
        id: settingsTarget
        function focusGroup(key) { fixture.operations.push(["group", key]) }
    }
    PagesManager { id: registry }
}''').encode(), QUrl.fromLocalFile(str(qml / "navigation-test-fixture.qml")))
    fixture = fixture_component.create()
    assert fixture is not None, fixture_component.errorString()
    context.setContextProperty("qmlapp", fixture)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml / "TabPages/Navigation/Navigation.qml")))
    navigation = component.create()
    assert navigation is not None, component.errorString()
    navigation.setParentItem(fixture)

    def js(code, obj=navigation):
        expression = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
        value = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        if isinstance(value, tuple):
            value = value[0]
        return value.toVariant() if hasattr(value, "toVariant") else value

    def jjson(code, obj=navigation):
        return json.loads(js("JSON.stringify(" + code + ")", obj))

    def descendants(item):
        for child in item.childItems():
            yield child
            yield from descendants(child)

    profiles = iter(((1040, 1, True), (720, 1, True), (600, 1.25, False), (1280, 1.25, True)))

    def observe(width, scale, document):
        items = list(descendants(navigation))
        # 没有 QQuickWindow 的帧循环，显式完成 Qt Quick 的待处理布局。
        for _ in range(3):
            for item in reversed(items):
                item.ensurePolished()
            for item in items:
                item.ensurePolished()
        workbench = next(item for item in items if item.objectName() == "navigationWorkbench")
        assert abs(navigation.width() - width) <= 1, (navigation.width(), width)
        tasks = [item for item in items
                 if item.objectName().startswith("navigationTask_") and item.property("visible")]
        keys = [item.objectName().removeprefix("navigationTask_") for item in tasks]
        assert keys == ["ScreenshotOCR", "BatchOCR", "BatchDOC", "QRCode"] + (["StructuredDocument"] if document else []), keys
        heading = next(item for item in items if item.objectName() == "navigationTaskHeading")
        card = next(item for item in items if item.objectName() == "navigationVersionCard")
        heading_bottom = heading.mapToItem(navigation, QPointF()).y() + heading.height()
        screenshot_top = tasks[0].mapToItem(navigation, QPointF()).y()
        left = min(item.mapToItem(navigation, QPointF()).x() for item in tasks)
        right = max(item.mapToItem(navigation, QPointF()).x() + item.width() for item in tasks)
        bottom = max(item.mapToItem(navigation, QPointF()).y() + item.height() for item in tasks)
        card_pos = card.mapToItem(navigation, QPointF())
        wide = width - 4 * sizes(scale)["spacing"] >= sizes(scale)["line"] * 46
        placement = {"width": width, "viewportWidth": workbench.property("availableWidth"),
                     "scale": scale, "document": document, "headingBottom": heading_bottom,
                     "screenshotTop": screenshot_top, "taskBottom": bottom,
                     "taskLeft": left, "taskRight": right, "versionX": card_pos.x(),
                     "versionY": card_pos.y(), "versionBottom": card_pos.y() + card.height()}
        assert min(screenshot_top, card_pos.y()) > heading_bottom, placement
        assert abs(card.height() - card.implicitHeight()) <= 1, placement
        if wide:
            assert card_pos.x() >= right - 1 and abs(card_pos.y() - screenshot_top) <= 1, placement
        else:
            assert abs(card_pos.x() - left) <= 1 and card_pos.y() >= bottom - 1, placement
        assert not any(item.objectName() == "navigationModelSettings" for item in items)
        plugin_button = next(item for item in descendants(card) if item.objectName() == "navigationPluginSettings")
        assert plugin_button.isVisible() and plugin_button.property("activeFocusOnTab")
        boxes = []
        for item in tasks:
            assert item.property("description") and item.property("activeFocusOnTab"), item.objectName()
            assert item.width() > 0 and item.height() > 0, item.objectName()
            assert item.width() <= navigation.width(), item.objectName()
            assert item.height() + 1 >= item.property("implicitHeight"), item.objectName()
            boxes.append({"key": item.objectName(), "width": item.width(), "height": item.height(),
                          "description": item.property("description")})
        js("qmlapp.globalConfigs.pluginStates=[]")
        assert not js("hasOcrPlugin")
        assert jjson("installedVersions") == ["Umi-OCR  " + about["version"]["string"]]
        js('qmlapp.globalConfigs.pluginStates=[{id:"cuda",name:"CUDA",version:"3.0.5",state:"disabled",capabilities:["ocr"]}]')
        assert not js("hasOcrPlugin") and "已禁用" in jjson("installedVersions")[1]
        js('qmlapp.globalConfigs.pluginStates=[{id:"cuda",name:"CUDA",version:"3.0.5",state:"ready",capabilities:["ocr"]}]')
        assert js("hasOcrPlugin")
        before = jjson("installedVersions")
        js('introText="控制焦点不改变版本区"')
        assert jjson("installedVersions") == before
        js("qmlapp.operations=[]")
        for item in tasks:
            item.clicked.emit()
        operations = jjson("qmlapp.operations")
        assert operations == [["task", 0, index] for index in [1, 2, 3, 4] + ([7] if document else [])], operations
        js("qmlapp.operations=[]")
        plugin_button.clicked.emit()
        assert jjson("qmlapp.operations") == [["open", "GlobalConfigsPage"], ["group", "plugins"]]
        assert js('summaryFor("# 标题\\n\\n第一段用途。\\n\\n支持格式：`png`")') == "第一段用途。"
        assert not app.allWindows()
        return {"width": width, "scale": scale, "tasks": boxes, "statesReactive": True,
                "versionCardPlacement": "alignedWithScreenshotTop" if wide else "belowLastCard",
                "placement": placement, "documentCard": document,
                "taskControlSignals": operations, "pluginShortcut": "plugins", "modelShortcutPresent": False}

    def step():
        try:
            width, scale, document = next(profiles)
        except StopIteration:
            app.quit()
            return
        context.setContextProperty("size_", sizes(scale))
        fixture.setProperty("width", width)
        fixture.setProperty("height", 760)
        fixture.setProperty("showDocumentCard", document)

        def check():
            try:
                cases.append(observe(width, scale, document))
            except Exception:
                failures.append(traceback.format_exc())
                app.quit()
                return
            QTimer.singleShot(0, step)

        QTimer.singleShot(40, check)

    QTimer.singleShot(0, step)
    QTimer.singleShot(15000, lambda: (failures.append("windowless scenario timeout"), app.quit()) if len(cases) < 4 else None)
    app.exec()
    warnings = [text for kind, text in messages if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)]
    if warnings:
        failures.append("QML warnings: " + repr(warnings))
    sources = [Path(__file__), qml / "TabPages/Navigation/Navigation.qml",
               qml / "TabPages/Navigation/NavigationTask.qml", qml / "TabPages/PagesManager.qml"]
    report = {"status": "PASS" if not failures and len(cases) == 4 else "FAIL",
              "mode": "real-qml-workbench-windowless", "runtime": str(data), "sourceRoot": str(source),
              "python": sys.version, "cases": cases, "failures": failures, "qwindowCount": len(app.allWindows()),
              "sourceSha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
              "limits": "真实QML布局及控件信号、模拟安装状态；不代替真实窗口输入、翻译矩阵、包内或模型验收。"}
    navigation.deleteLater()
    fixture.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qInstallMessageHandler(previous)
    handle.close()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert sys.flags.isolated and sys.flags.dont_write_bytecode
    assert args.output.parent.is_dir() and not args.output.exists()
    report = run(args.data_root.resolve(), args.source_root.resolve())
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "cases": len(report["cases"]), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
