"""真实 Qt 序列／菜单回归，不启动 OCR、不捕获桌面。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data, output = args.data.resolve(), args.output.resolve()
    os.chdir(output.parent)
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    sys.path[:0] = [str(data / "site-packages"), str(data / "dependencies.zip")]
    dll = os.add_dll_directory(str(data / "site-packages/PySide6"))
    from PySide6.QtCore import QObject, QUrl, Slot
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    class Values(QObject):
        @Slot(int, result="QVariant")
        def result(self, kind):
            return {"code": 100, "warnings": ([], ["真实警告", {"message": "另一个警告"}], [[], None])[kind]}

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication([])
    engine = QQmlEngine()
    engine.addImportPath(str(data / "site-packages/PySide6/qml"))
    context = engine.rootContext()
    values = Values()
    context.setContextProperty("values", values)
    context.setContextProperty("qmlapp", {"enabledEffect": False})
    context.setContextProperty("theme", {**{key: QColor("#333333") for key in (
        "textColor", "subTextColor", "bgColor", "specialBgColor", "specialTextColor", "noColor", "yesColor",
        "coverColor1", "coverColor2", "coverColor3", "coverColor4")}, "fontFamily": "Arial", "dataFontFamily": "Arial"})
    context.setContextProperty("size_", {"line": 24, "smallLine": 16, "text": 14, "smallText": 12,
        "spacing": 8, "smallSpacing": 4, "baseRadius": 4, "btnRadius": 4, "panelRadius": 4})
    widgets = (ROOT / "UmiOCR-data/qt_res/qml/Widgets").as_uri()
    component = QQmlComponent(engine)
    component.setData(f'''import QtQuick
import QtQuick.Controls
import "{widgets}" as W
import "{widgets}/ResultLayout" as R
import "{widgets}/Sequence.js" as S
ApplicationWindow {{
    width: 600; height: 500
    property int invoked: 0
    W.Menu_ {{
        id: menu
        objectName: "legacyMenu"
        menuList: [[() => invoked++, "复制图片", "textColor", true, "", [], "copyImage"],
            {{text: "子菜单", children: [{{text: "保存", action: () => invoked += 10}}]}}]
    }}
    R.ResultsTableView {{ id: records; objectName: "records"; width: 500; height: 400; autoToBottom: false }}
    function finiteSequence() {{ return !S.isSequence({{length: Infinity}}) && !S.isSequence({{length: NaN}}) }}
    function emptyNotice() {{ return records.resultNotice(values.result(0)) }}
    function realNotice() {{ return records.resultNotice(values.result(1)) }}
    function nestedNotice() {{ return records.resultNotice(values.result(2)) }}
    function invokeLegacy() {{ menu.activate(menu.menuList[0], 0) }}
    function openChild() {{ menu.activate(menu.menuList[1], 20); return menu.childMenu_ !== null }}
    function closeMenus() {{ menu.closeChild(); menu.close() }}
}}
'''.encode(), QUrl("inline:sequence-boundary.qml"))
    while component.isLoading():
        app.processEvents()
    root = component.create()
    assert root is not None, component.errorString()
    engine.globalObject().setProperty("testRoot", engine.newQObject(root))
    records = root.findChild(QObject, "records")
    menu = root.findChild(QObject, "legacyMenu")
    engine.globalObject().setProperty("records", engine.newQObject(records))

    def js(code):
        result = engine.evaluate(code)
        assert not result.isError(), result.toString()
        app.processEvents()
        return result.toVariant()

    assert js("testRoot.finiteSequence()") is True
    assert js("testRoot.emptyNotice().label") == ""
    assert js("testRoot.nestedNotice().label") == ""
    assert js("testRoot.realNotice().warningText") == "真实警告\n另一个警告"
    assert js('records.resultNotice({code: 100, partial: true, warnings: []}).label') == "部分结果"
    assert js('records.resultNotice({code: 100, warnings: ["[]"]}).warningText') == "[]", "不能删除真实字符串警告"
    menu.open()
    app.processEvents()
    def visual_items(item):
        yield item
        for child in item.childItems():
            yield from visual_items(child)
    items = list(visual_items(menu.property("contentItem")))
    button = next((item for item in items if item.objectName() == "copyImage"), None)
    assert button is not None, [(item.metaObject().className(), item.objectName()) for item in items]
    assert button.property("enabled") is True
    assert button.property("contentItem").property("text") == "复制图片"
    js("testRoot.invokeLegacy()")
    assert root.property("invoked") == 1, "Repeater 转换不能丢失 JS 回调"
    assert js("testRoot.openChild()") is True
    js("testRoot.closeMenus()")
    for index, score in enumerate((0, 0.95, None), 1):
        value = {"code": 100, "data": [{"text": "正文"}], "timestamp": index, "time": 0.5,
                 "score": score, "confidenceSupported": score is not None}
        js(f"records.addOcrResult({json.dumps(value)})")
        title = js(f'records.getResult("", {index}).title')
        assert ("置信度 0.00" if score == 0 else "置信度 0.95" if score else "此模型不提供识别置信度") in title
    output.write_text(json.dumps({"passed": True, "checks": ["Python QVariantList 警告", "真实菜单文字与回调", "子菜单", "零分与置信度能力"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("真实 Qt 序列、菜单及置信度回归通过。")
    root.deleteLater()
    app.processEvents()
    del dll


if __name__ == "__main__":
    main()
