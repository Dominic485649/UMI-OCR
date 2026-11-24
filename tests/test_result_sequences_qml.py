"""真实 Qt 序列／菜单回归，不启动 OCR、不捕获桌面。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
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
    assert output.parent.is_dir() and not output.exists(), "不覆盖旧验证记录"
    os.chdir(output.parent)
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    sys.path[:0] = [str(data / "site-packages"), str(data / "dependencies.zip")]
    dll = os.add_dll_directory(str(data / "site-packages/PySide6"))
    from PySide6.QtCore import QObject, QUrl, Slot
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import QJSEngine, QQmlComponent, QQmlEngine, QQmlExpression, qmlRegisterType
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
    fixture_component = QQmlComponent(engine)
    fixture_component.setData(b'''import QtQuick
Item {
    property bool enabledEffect:false
    property var copies:[]
    property QtObject tab:null
    property QtObject utilsConnector:QtObject { function copyText(text) { copies.push(text) } }
    property QtObject popup:QtObject { function simple(title,text) {} }
}''', QUrl("inline:result-safety-fixture.qml"))
    while fixture_component.isLoading():
        app.processEvents()
    fixture = fixture_component.create()
    assert fixture is not None, fixture_component.errorString()
    context.setContextProperty("qmlapp", fixture)
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
    # 直接加载文件使表达式处于该组件的词法上下文；不从外部内联组件访问私有id。
    guards_component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "UmiOCR-data/qt_res/qml/Widgets/ResultLayout/ResultsTableView.qml")))
    while guards_component.isLoading():
        app.processEvents()
    records = guards_component.createWithInitialProperties({"width":720,"height":400,"autoToBottom":False})
    assert records is not None, guards_component.errorString()
    records.setParent(fixture)

    def qml_js(obj, code):
        expression = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
        value = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        if isinstance(value, tuple): value = value[0]
        return value.toVariant() if hasattr(value, "toVariant") else value

    def titles():
        return json.loads(qml_js(records, "JSON.stringify(Array.from({length:resultsModel.count},(_,i)=>resultsModel.get(i).title))"))

    def add(title, timestamp):
        qml_js(records, "addOcrResult(" + json.dumps({"code":100,"time":.1,"timestamp":timestamp,
            "title":title,"data":[{"text":title}]}) + ")")

    qml_js(records, "tableMouseArea.selectAllDel();historyLimit=2")
    add("A", 1); add("B", 2)
    qml_js(records, "tableMouseArea.startIndex=tableMouseArea.endIndex=0;tableMouseArea.startTextIndex=0;tableMouseArea.endTextIndex=1")
    add("C", 3)
    assert titles() == ["B", "C"]
    assert qml_js(records, "tableMouseArea.startIndex") == -1, "到期选区不能无声转移到B"
    qml_js(records, "tableMouseArea.selectDel()")
    assert titles() == ["B", "C"], "到期选区不能误删未选中的B"
    qml_js(records, "tableMouseArea.startIndex=tableMouseArea.endIndex=1;tableMouseArea.startTextIndex=0;tableMouseArea.endTextIndex=1")
    add("D", 4)
    assert titles() == ["C", "D"] and qml_js(records, "tableMouseArea.startIndex") == 0, "存活选区应随头部裁剪移位"
    before_bytes = qml_js(records, "historyBytes")
    qml_js(records, "tableMouseArea.selectDel()")
    assert titles() == ["D"] and qml_js(records, "historyBytes") < before_bytes
    assert qml_js(records, "historyBytes===resultsModel.get(0).source.length*2"), "手动删除须精确归还历史预算"
    qml_js(records, "tableMouseArea.initIndexes();tableMouseArea.selectCopy()")
    qml_js(records, "tableMouseArea.selectAllDel();tableMouseArea.selectCopy()")
    assert qml_js(records, "historyBytes") == 0, "清空后预算必须归零"

    # 在真实Qt便携设置桥接下验证V4Sequence恢复，不把Python list当JS Array。
    spec = importlib.util.spec_from_file_location("sequence_portable_settings", ROOT / "UmiOCR-data/py_src/utils/portable_settings.py")
    settings_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(settings_module)
    settings_path = output.with_name(output.stem + "-tabs.settings")
    assert not settings_path.exists()
    settings = settings_module.PortableSettings(str(settings_path))
    settings.setValue("TabPageManager", "openPageList", ["BatchOCR", "BatchDOC"])
    settings.setValue("TabPageManager", "showPageIndex", 1)
    settings.sync()
    context.setContextProperty("UmiSettings", settings)
    class PageConnector(QObject): pass
    qmlRegisterType(PageConnector, "TagPageConnector", 1, 0, "TagPageConnector")
    tabs_component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "UmiOCR-data/qt_res/qml/TabView_/TabViewManager.qml")))
    tabs = tabs_component.create()
    assert tabs is not None, tabs_component.errorString()
    tabs.setParent(fixture)
    fixture.setProperty("tab", tabs)
    assert json.loads(qml_js(tabs, "JSON.stringify(openPageList)")) == ["BatchOCR", "BatchDOC"]
    assert qml_js(tabs, "showPageIndex") == 1
    for origin, target, active, expected in ((0,2,1,0),(2,0,1,2),(1,2,1,2),(2,0,0,1)):
        qml_js(tabs, '''bar=({moveTab:function(){},showTab:function(){},changeTab:function(){}});
page.pageList=[{info:{key:'A'},obj:({name:'A'})},{info:{key:'B'},obj:({name:'B'})},{info:{key:'C'},obj:({name:'C'})}];
openPageList=['A','B','C'];showPageIndex=''' + str(active))
        qml_js(tabs, f"moveTabPage({origin},{target})")
        assert qml_js(tabs, "showPageIndex") == expected, (origin,target,active,expected)
    qml_js(tabs, '''page.pageList=[
{info:{key:'A',pluginKey:'plugin-a'},infoIndex:7,obj:({name:'A',enabled:true,showPage:function(){}})},
{info:{key:'B',pluginKey:'plugin-b'},infoIndex:8,obj:({name:'B',enabled:true,showPage:function(){}})}];
page.registerPluginPages([{key:'B',pluginKey:'plugin-b',title:'B'}]);''')
    assert qml_js(tabs, "pageList[0].infoIndex") == -1
    assert qml_js(tabs, "openTabPageByKey('B').name") == "B", "禁用A后打开B不能误命中A的旧索引"

    # 原样执行真实QML按键处理器；不读写系统剪贴板或真实结果记录。
    key_source = (ROOT / "UmiOCR-data/qt_res/qml/Widgets/ResultLayout/ResultTextContainer.qml").read_text("utf-8-sig")
    def body(marker):
        start = key_source.index("{", key_source.index(marker)); end = start + 1; depth = 1
        while depth:
            depth += (key_source[end] == "{") - (key_source[end] == "}")
            end += 1
        return key_source[start+1:end-1]
    keys = QJSEngine()
    setup = '''var Qt={ControlModifier:67108864,Key_A:65,Key_C:67,Key_D:68};
var keyDoubleTime=300,lastUpTime=-1,lastKey=-1,controlledKeys={},listeningKeys=[65,67,68],clearCalls=0;
var resultRoot={selectAllDel:function(){clearCalls++},selectAll:function(){clearCalls++},copyAll:function(){clearCalls++}};
function released(event){''' + body("Keys.onReleased:") + '''}
function pressed(event){''' + body("Keys.onPressed:") + '''}
'''
    patterns = {
        "plain-d-then-ctrl-d": ("released({key:68,modifiers:0});pressed({key:68,modifiers:67108864})", 0),
        "double-ctrl-d": ("pressed({key:68,modifiers:67108864});released({key:68,modifiers:67108864});pressed({key:68,modifiers:67108864})", 1),
        "held-ctrl-d": ("released({key:68,modifiers:67108864,isAutoRepeat:true});pressed({key:68,modifiers:67108864,isAutoRepeat:true})", 0),
        "clock-moved-back": ("lastUpTime=Date.now()+1000;lastKey=68;pressed({key:68,modifiers:67108864})", 0),
        "ctrl-released-before-d": ("pressed({key:68,modifiers:67108864});released({key:68,modifiers:0});pressed({key:68,modifiers:67108864})", 1),
        "plain-d-pressed-before-ctrl": ("pressed({key:68,modifiers:0});released({key:68,modifiers:67108864});pressed({key:68,modifiers:67108864})", 0),
        "ctrl-released-before-c": ("pressed({key:67,modifiers:67108864});released({key:67,modifiers:0});pressed({key:67,modifiers:67108864})", 1),
        "ctrl-released-before-a": ("pressed({key:65,modifiers:67108864});released({key:65,modifiers:0});pressed({key:65,modifiers:67108864})", 1),
        "overlapping-a-c": ("pressed({key:65,modifiers:67108864});pressed({key:67,modifiers:67108864});released({key:65,modifiers:67108864});released({key:67,modifiers:67108864});pressed({key:67,modifiers:67108864})", 1),
        "overlapping-c-a": ("pressed({key:67,modifiers:67108864});pressed({key:65,modifiers:67108864});released({key:67,modifiers:67108864});released({key:65,modifiers:67108864});pressed({key:65,modifiers:67108864})", 1),
    }
    for label, (pattern, expected) in patterns.items():
        value = keys.evaluate(setup + pattern + ";clearCalls")
        assert not value.isError(), value.toString()
        assert value.toInt() == expected, (label, value.toInt(), expected)
    sources = [Path(__file__), ROOT / "UmiOCR-data/qt_res/qml/Widgets/ResultLayout/ResultsTableView.qml",
        ROOT / "UmiOCR-data/qt_res/qml/Widgets/ResultLayout/ResultTextContainer.qml",
        ROOT / "UmiOCR-data/qt_res/qml/TabView_/TabViewManager.qml", ROOT / "UmiOCR-data/qt_res/qml/TabPages/PagesManager.qml"]
    output.write_text(json.dumps({"passed": True, "checks": ["Python QVariantList 警告", "真实菜单文字与回调", "子菜单", "零分与置信度能力",
        "过期选区不误删", "存活选区移位", "删除预算归还", "无选区复制", "便携标签恢复", "跨活动页拖动", "动态插件页稳定键", "Ctrl组合键清空保护"],
        "keyCases":list(patterns), "sourceSha256":{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
        "limits":"受控QML和Qt设置；按键为提取的真实处理器JS，不替代完整原生结果编辑交互验收。"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("真实 Qt 序列、结果数据保护、标签恢复及按键处理回归通过。")
    root.deleteLater()
    app.processEvents()
    del dll


if __name__ == "__main__":
    main()
