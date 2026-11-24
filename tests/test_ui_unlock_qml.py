"""真实 PagesManager / TagPageConnector 的 UI 门控回归，无窗口、无截图、无推理。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(runtime, output, work):
    spec = importlib.util.spec_from_file_location('unlock_qml_source_helpers', ROOT / 'tests/test_ignore_area_qml.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    handles = helper.configure_source_runtime(runtime, ROOT / 'UmiOCR-data')
    from PySide6.QtCore import QCoreApplication, QEvent, QUrl, QtMsgType, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine, qmlRegisterType
    from py_src.utils import ui_unlock
    from py_src.tag_pages import page_registry, tag_pages_connector

    if work.exists() or output.exists():
        raise FileExistsError('QML检查工作目录及结果须全新')
    work.mkdir()
    view = work / 'View.qml'
    view.write_text('import QtQuick 2.15\nItem { property string ctrlKey; property var connector; property string pluginKey; function showPage() {} }\n', encoding='utf-8')
    app = QGuiApplication(['ui-unlock-source-qml'])
    qmlRegisterType(tag_pages_connector.TagPageConnector, 'TagPageConnector', 1, 0, 'TagPageConnector')
    engine = QQmlEngine()
    engine.addImportPath(str(runtime / 'site-packages/PySide6/qml'))
    messages, calls = [], []
    previous = qInstallMessageHandler(lambda kind, _context, text: messages.append((kind, text)))
    source = ROOT / 'UmiOCR-data/qt_res/qml/TabPages/PagesManager.qml'
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(source)))
    while component.isLoading():
        app.processEvents()
    root = component.create()
    assert root is not None, component.errorString()
    engine.globalObject().setProperty('pages', engine.newQObject(root))
    class Controller:
        def __init__(self, key, connector):
            calls.append(key)
        def close(self):
            pass
    page_registry.registerPluginPageClass('StructuredDocument', lambda: Controller,
        requiredFeature=ui_unlock.DOCUMENT_UI_FEATURE)
    def evaluate(code):
        value = engine.evaluate(code)
        assert not value.isError(), value.toString()
        return value.toVariant()
    def checkpoint():
        app.processEvents()
        assert not app.allWindows(), '此定向检查不得创建窗口'
        failures = [text for kind, text in messages if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)]
        assert not failures, failures
    infos = [{'key': 'StructuredDocument', 'url': (work / 'MustNotLoad.qml').as_uri(),
              'pluginKey': 'win32_PaddleOCRVL_1_6', 'needController': True, 'title': 'doc'},
             {'key': 'OtherPage', 'url': view.as_uri(), 'needController': False, 'title': 'other'}]
    evaluate('pages.infoList = ' + json.dumps(infos))
    ui_unlock._state = ui_unlock.UiUnlockState(False, 'missing')
    assert evaluate('pages.addPage(-1, 0)') is False
    assert evaluate('pages.isSavedPageAvailable("StructuredDocument")') is False
    assert evaluate('pages.isSavedPageAvailable("file:///old/plugins/StructuredDocument.qml")') is False
    assert evaluate('pages.isSavedPageAvailable("OtherPage")') is True
    assert not calls
    assert evaluate('pages.pageList.length') == 0
    connector = tag_pages_connector.TagPageConnObj
    assert connector.addPage('StructuredDocument') == ''
    assert connector.addSimplePage('StructuredDocument') == ''
    assert connector.isPageAvailable('BatchDOC')
    assert evaluate('pages.addPage(-1, 1)') is True
    checkpoint()
    ui_unlock._state = ui_unlock.UiUnlockState(True, 'unlocked-test')
    evaluate('pages.infoList[0].url = ' + json.dumps(view.as_uri()))
    assert evaluate('pages.addPage(-1, 0)') is True
    assert len(calls) == 1
    assert evaluate('pages.pageList.length') == 2
    checkpoint()
    ui_unlock._state = ui_unlock.UiUnlockState(False, 'invalid')
    assert evaluate('pages.addPage(-1, 0)') is False
    assert connector.addPage('StructuredDocument') == ''
    assert len(calls) == 1, '已经缓存的控制器类不能绕过门控'
    checkpoint()
    result = {'status': 'PASS', 'checks': ['旧页面元信息不能在未解锁时创建组件',
        'Python控制器和简单页入口均受控', '有效能力允许真实QML页面和控制器创建',
        '已缓存类仍先检查能力', '其他页面与BatchDOC保持可用'],
        'scope': '执行仓库真实PagesManager和TagPageConnector；能力值受控，真实DLL另行验证，不冒充GPU或原生主窗口验收。',
        'qwindowCount': len(app.allWindows()), 'desktopCapture': 'NOT_RUN',
        'sourceSha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (source, ROOT / 'UmiOCR-data/py_src/tag_pages/tag_pages_connector.py')}}
    root.deleteLater()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    qInstallMessageHandler(previous)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    run(args.runtime.resolve(), args.output.resolve(), args.work.resolve())
