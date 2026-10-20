import argparse
import importlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IGNORE_KEYS = ("tbpu.ignoreArea", "tbpu.ignoreRangeStart", "tbpu.ignoreRangeEnd")


def configure_source_runtime(data_root, source_root):
    """仅借用便携依赖，QML/Python 业务代码始终从指定源码目录加载。"""
    sys.path[:] = [entry for entry in sys.path if "app.zip" not in entry.lower()]
    sys.path[:0] = [
        str(source_root),
        str(source_root / "py_src" / "imports"),
        str(data_root / "site-packages"),
        str(data_root / "dependencies.zip"),
    ]
    handles = []
    if os.name == "nt":
        handles.append(os.add_dll_directory(data_root / "site-packages" / "PySide6"))
        os.environ["QT_QPA_PLATFORM"] = "windows"
    return handles


def wait_until(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise TimeoutError("当前源码 QML 对象未在时限内就绪。")


def plain(value):
    if hasattr(value, "toVariant"):
        return plain(value.toVariant())
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def test_preview_connector_races(app, source_root):
    """真实 SimpleMission/CallFunc，屏障控制工作完成与 Qt queued 交付的先后。"""
    from threading import Event, Thread
    from types import SimpleNamespace
    from unittest.mock import patch

    from PySide6.QtCore import QObject, Slot

    connector_module = importlib.import_module("py_src.mission.doc_preview_connector")
    mission_module = importlib.import_module("py_src.mission.mission_doc")
    pool = importlib.import_module("py_src.utils.thread_pool").GlobalThreadPool
    assert Path(connector_module.__file__).resolve() == source_root / "py_src/mission/doc_preview_connector.py"
    real_dispatch = connector_module.CallFunc
    docs, blockers, connectors = [], {}, []
    cases = []

    class FakeDoc:
        page_count = 1
        is_encrypted = False

        def __init__(self, path):
            self.path = path
            self.closed = False
            self.close_count = 0
            docs.append(self)

        def __getitem__(self, _page):
            return self

        @property
        def rect(self):
            return (0, 0, 4, 3)

        def get_pixmap(self, matrix):
            assert not self.closed
            if self.path in blockers:
                started, release = blockers[self.path]
                started.set()
                assert release.wait(5), "受控预览渲染屏障未释放。"
            color = (0, 0, 255) if self.path.startswith("B") else (255, 0, 0)
            return SimpleNamespace(width=4, height=3, stride=12, samples=bytes(color * 12))

        def close(self):
            self.closed = True
            self.close_count += 1

    def open_doc(path):
        if path == "missing.pdf":
            raise OSError("受控打开失败")
        return FakeDoc(path)

    fake_fitz = SimpleNamespace(open=open_doc, Identity=object(), Matrix=lambda *args: args)

    class Cache:
        def __init__(self):
            self.entries = {}
            self.count = 0

        def addPixmap(self, pixmap):
            self.count += 1
            img_id = f"preview-race-{self.count}"
            self.entries[img_id] = {
                "color": pixmap.toImage().pixelColor(0, 0).name(),
                "main_thread": app.thread().isCurrentThread(),
            }
            return img_id

    cache = Cache()

    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.images = []
            self.ocr = []

        @Slot(str)
        def image(self, img_id):
            assert app.thread().isCurrentThread()
            self.images.append(img_id)

        @Slot("QVariant")
        def result(self, value):
            assert app.thread().isCurrentThread()
            self.ocr.append(plain(value))

    def new_connector():
        connector, receiver = connector_module.DocPreviewConnector(), Receiver()
        connector.previewImg.connect(receiver.image)
        connector.previewOcr.connect(receiver.result)
        connectors.append((connector, receiver))
        return connector, receiver

    def workers_done():
        # 此测试进程仅有受控渲染任务；完成屏障不转动主线程事件循环。
        assert pool.waitForDone(5000), "文档预览工作线程未完成。"

    def worker_call(func):
        errors = []

        def run():
            try:
                func()
            except BaseException as exc:
                errors.append(exc)

        thread = Thread(target=run, daemon=True)
        thread.start()
        thread.join(5)
        assert not thread.is_alive(), "受控 OCR 回调线程未完成。"
        assert not errors, errors

    def only_blue(receiver):
        assert len(receiver.images) == 1, receiver.images
        assert len(cache.entries) == 1, cache.entries
        assert cache.entries[receiver.images[0]] == {"color": "#0000ff", "main_thread": True}

    with patch.dict(sys.modules, {"fitz": fake_fitz}), patch.object(connector_module, "PixmapProvider", cache):
        try:
            # A 已进入渲染后 close/openB，replace 只能移除 pending，不能取消 A。
            connector, receiver = new_connector()
            started, release = Event(), Event()
            blockers["A-inflight.pdf"] = (started, release)
            connector.preview("A-inflight.pdf", 1, "")
            assert started.wait(5)
            connector.clear()
            connector.preview("B-current.pdf", 1, "")
            release.set()
            workers_done()
            assert receiver.images == []
            assert cache.entries == {}  # stale 结果不能提前进入 Pixmap 缓存。
            app.processEvents()
            only_blue(receiver)
            assert next(doc for doc in docs if doc.path == "A-inflight.pdf").closed
            connector.clear()
            workers_done()
            app.processEvents()
            cases.append("inflight_A_close_open_B")

            # A 先完成并等待主线程交付，再打开 B；强制 B/A 逆序进入真实 Qt 队列。
            cache.entries.clear()
            held = []
            collector = SimpleNamespace(now=lambda func, *args: held.append((func, args)))
            connector, receiver = new_connector()
            with patch.object(connector_module, "CallFunc", collector):
                connector.preview("A-queued.pdf", 1, "")
                workers_done()
                connector.clear()
                connector.preview("B-queued.pdf", 1, "")
                workers_done()
                assert len(held) == 2, held
                worker_call(lambda: [real_dispatch.now(func, *args) for func, args in reversed(held)])
                assert receiver.images == []
                app.processEvents()
                only_blue(receiver)
                connector.clear()
                workers_done()
            cases.append("queued_render_B_before_A")

            # worker 已 post，clear 才发生：只在 worker emit 前判断挡不住此竞态。
            cache.entries.clear()
            connector, receiver = new_connector()
            connector.preview("A-clear-after-post.pdf", 1, "")
            workers_done()
            connector.clear()
            workers_done()
            app.processEvents()
            assert receiver.images == [] and cache.entries == {}
            connector.preview("missing.pdf", 1, "")
            workers_done()
            connector.clear()
            workers_done()
            app.processEvents()
            assert receiver.images == [] and cache.entries == {}
            cases.append("clear_after_queued_render_and_error")

            submitted = []

            def submit(info, path, page_range, password=""):
                submitted.append((info, path, page_range, password))
                return "controlled-preview-ocr"

            def ocr_result(text):
                return {"code": 100, "data": [{"text": text, "box": [[1, 1], [2, 1], [2, 2], [1, 2]]}]}

            def send_result(job, text):
                value = ocr_result(text)
                worker_call(lambda: job["onGet"](job, 0, value))
                return value

            with patch.object(mission_module.MissionDOC, "addMission", submit):
                connector, receiver = new_connector()
                connector.preview("ocr.pdf", 1, "")
                workers_done()
                app.processEvents()
                connector.ocr("ocr.pdf", 1, "", {"tbpu.ignoreArea": [[[0, 0], [1, 0], [1, 1], [0, 1]]]})
                old = submitted[-1][0]
                send_result(old, "旧参数已排队")
                worker_call(lambda: old["onEnd"](old, "[Error] 旧参数异常"))
                connector.ocr("ocr.pdf", 1, "", {"tbpu.ignoreArea": None})
                newest = submitted[-1][0]
                assert newest["argd"]["tbpu.ignoreArea"] is None
                value = send_result(newest, "新参数")
                value["data"][0]["text"] = "工作回调后的外部改动"
                app.processEvents()
                assert [item[2]["data"][0]["text"] for item in receiver.ocr] == ["新参数"]
                cases.append("same_page_new_args_supersede_queued_old_ocr")

                receiver.ocr.clear()
                connector.ocr("ocr.pdf", 1, "", {"revision": "old"})
                old = submitted[-1][0]
                connector.ocr("ocr.pdf", 1, "", {"revision": "new"})
                newest = submitted[-1][0]
                send_result(newest, "新参数先完成")
                send_result(old, "旧参数晚完成")
                app.processEvents()
                assert [item[2]["data"][0]["text"] for item in receiver.ocr] == ["新参数先完成"]
                cases.append("same_page_new_ocr_before_old_ocr")

                receiver.ocr.clear()
                connector.ocr("ocr.pdf", 1, "", {})
                job = submitted[-1][0]
                send_result(job, "clear 前排队")
                worker_call(lambda: job["onEnd"](job, "[Error] clear 前异常"))
                connector.clear()
                workers_done()
                app.processEvents()
                assert receiver.ocr == []
                cases.append("clear_after_queued_ocr_and_error")

                connector.preview("ocr.pdf", 1, "")
                workers_done()
                app.processEvents()
                connector.ocr("ocr.pdf", 1, "", {})
                send_result(submitted[-1][0], "换文档前排队")
                connector.preview("B-ocr.pdf", 1, "")
                workers_done()
                app.processEvents()
                assert receiver.ocr == []
                connector.ocr("B-ocr.pdf", 1, "", {})
                job = submitted[-1][0]
                worker_call(lambda: job["onEnd"](job, "[Error] 当前请求异常"))
                app.processEvents()
                assert receiver.ocr == [["B-ocr.pdf", -1, {"code": 103, "data": "[Error] 当前请求异常"}]]
                cases.append("new_preview_invalidates_old_ocr_preserves_current_error")
        finally:
            for _started, release in blockers.values():
                release.set()
            for connector, _receiver in connectors:
                connector.clear()
            workers_done()
            app.processEvents()
        assert all(doc.closed and doc.close_count == 1 for doc in docs), [(doc.path, doc.close_count) for doc in docs]
    return cases


def main():
    parser = argparse.ArgumentParser(description="当前源码忽略区域逻辑/几何回归，非系统鼠标手势验收。")
    parser.add_argument("data_root", type=Path, help="仅提供便携 Python/Qt 依赖的 UmiOCR-data")
    parser.add_argument("--source-root", type=Path, default=ROOT / "UmiOCR-data")
    args = parser.parse_args()
    data_root, source_root = args.data_root.resolve(), args.source_root.resolve()
    assert (source_root / "qt_res" / "qml" / "Widgets" / "IgnoreArea" / "ImageWithIgnore.qml").is_file()
    handles = configure_source_runtime(data_root, source_root)

    import PySide6
    from PySide6.QtCore import (
        QCoreApplication, QEvent, QObject, QPointF, Property, Qt, QUrl, Signal, Slot,
        qInstallMessageHandler,
    )
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QMouseEvent, QPixmap
    from PySide6.QtQml import QQmlComponent, QQmlEngine, qmlRegisterType
    from PySide6.QtQuick import QQuickImageProvider, QQuickItem, QQuickWindow
    from PySide6.QtQuickControls2 import QQuickStyle

    # 不加载 ui.rcc，不使用 QtTest，也不假定便携包包含 offscreen 插件。
    qml_errors = []
    error_markers = ("TypeError", "ReferenceError", "Unable to assign", "Binding loop", "Cannot assign")

    def message_handler(_kind, _context, message):
        if any(marker in message for marker in error_markers):
            qml_errors.append(message)

    old_handler = qInstallMessageHandler(message_handler)
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication.instance() or QGuiApplication(["ignore-area-source-qml-test"])
    app.setQuitOnLastWindowClosed(False)
    connector_races = test_preview_connector_races(app, source_root)

    class GlobalConfigsStub(QObject):
        @Slot(str, result="QVariant")
        def getValue(self, key):
            return {} if key == "window.doubleLayout" else True

        @Slot(str, "QVariant")
        def setValue(self, _key, _value):
            pass

    class PopupStub(QObject):
        @Slot(str, str)
        @Slot(str, str, str)
        def simple(self, *_args):
            pass

        @Slot(str, str, str)
        def message(self, *_args):
            pass

    class QmlAppStub(QObject):
        def __init__(self):
            super().__init__()
            self._configs = GlobalConfigsStub(self)
            self._popup = PopupStub(self)

        @Property(bool, constant=True)
        def enabledEffect(self):
            return False

        @Property(QObject, constant=True)
        def globalConfigs(self):
            return self._configs

        @Property(QObject, constant=True)
        def popup(self):
            return self._popup

    class DocPreviewStub(QObject):
        previewImg = Signal(str)
        previewOcr = Signal("QVariant")
        instances = []

        def __init__(self, parent=None):
            super().__init__(parent)
            self.preview_calls = []
            self.ocr_calls = []
            self.clear_count = 0
            self.instances.append(self)

        @Slot(str, int, str)
        def preview(self, path, page, password):
            self.preview_calls.append((path, page, password))
            self.previewImg.emit(f"page-{page}")

        @Slot(str, int, str, "QVariant")
        def ocr(self, path, page, password, argd):
            self.ocr_calls.append((path, page, password, plain(argd)))

        @Slot()
        def clear(self):
            self.clear_count += 1

    class PreviewImageProvider(QQuickImageProvider):
        def __init__(self):
            super().__init__(QQuickImageProvider.ImageType.Pixmap)
            self.image = QPixmap(800, 400)
            self.image.fill(QColor("white"))
            self.empty = QPixmap(1, 1)
            self.empty.fill(Qt.GlobalColor.transparent)

        def requestPixmap(self, path, _size=None, _requested=None):
            return self.image if "/" in path else self.empty

    qmlRegisterType(DocPreviewStub, "DocPreviewConnector", 1, 0, "DocPreviewConnector")
    engine = QQmlEngine()
    engine.addImportPath(str(data_root / "site-packages" / "PySide6" / "qml"))
    engine.addImageProvider("pixmapprovider", PreviewImageProvider())
    context = engine.rootContext()
    context.setContextProperty("theme", {
        "bgColor": QColor("white"), "textColor": QColor("#111111"),
        "subTextColor": QColor("#555555"), "coverColor1": QColor("#eeeeee"),
        "coverColor2": QColor("#dddddd"), "coverColor3": QColor("#aaaaaa"),
        "coverColor4": QColor("#55000000"), "specialBgColor": QColor("#eeeeee"),
        "specialTextColor": QColor("#1166cc"), "noColor": QColor("#cc3333"),
        "yesColor": QColor("#339933"), "fontFamily": "Arial", "dataFontFamily": "Arial",
    })
    context.setContextProperty("size_", {
        "line": 24, "smallLine": 16, "text": 14, "smallText": 12,
        "spacing": 8, "smallSpacing": 4, "btnRadius": 4, "panelRadius": 4,
    })
    qml_app = QmlAppStub()
    main_container = QQuickItem()
    context.setContextProperty("qmlapp", qml_app)
    context.setContextProperty("mainContainer", main_container)
    ignore_dir = (source_root / "qt_res" / "qml" / "Widgets" / "IgnoreArea").as_uri()
    doc_dir = (source_root / "qt_res" / "qml" / "TabPages" / "BatchDOC").as_uri()
    component = QQmlComponent(engine)
    component.setData(f'''
import QtQuick
import "{ignore_dir}" as Ignore
import "{doc_dir}" as Documents
Item {{
    id: root
    width: 1000; height: 720
    property var callbackInfo: undefined
    property alias configValues: configs.values
    QtObject {{
        id: configs
        property var values: ({{
            "tbpu.ignoreArea": [[[1,1],[5,1],[5,5],[1,5]]],
            "tbpu.ignoreRangeStart": 1, "tbpu.ignoreRangeEnd": -1,
            "tbpu.parser": "original-parser", "unchanged": 42
        }})
        function getValue(key) {{ return values[key] }}
        function getValueDict() {{ return values }}
        function setValue(key, value) {{
            let next = Object.assign({{}}, values)
            next[key] = value
            values = next
        }}
    }}
    Ignore.ImageWithIgnore {{
        id: viewer
        objectName: "viewer"
        width: 600; height: 400
        property int boundBoxCount: ig1Boxes.length
    }}
    Documents.PreviewDoc {{
        id: preview
        objectName: "preview"
        anchors.fill: parent
        configsComp: configs
        updateInfo: (path, fields) => {{
            root.callbackInfo = {{path: path, fields: fields,
                configsAtCallback: Object.assign({{}}, configs.values)}}
        }}
    }}
    Ignore.IgnoreArea {{
        objectName: "editor"
        anchors.fill: parent
        configsComp: configs
        configKey: "tbpu.ignoreArea"
    }}
}}
'''.encode("utf-8"), QUrl("inline:ignore-area-current-source-test.qml"))
    wait_until(app, lambda: not component.isLoading())
    root = component.create()
    if root is None:
        raise RuntimeError(component.errorString())
    viewer = root.findChild(QQuickItem, "viewer")
    preview = root.findChild(QQuickItem, "preview")
    editor = root.findChild(QQuickItem, "editor")
    assert all((viewer, preview, editor))
    for name, obj in (("root", root), ("viewer", viewer), ("preview", preview), ("editor", editor)):
        engine.globalObject().setProperty(name, engine.newQObject(obj))

    def evaluate(expression):
        result = engine.evaluate(expression)
        assert not result.isError(), (result.toString(), result.property("stack").toString())
        return plain(result)

    def bind(name, obj):
        engine.globalObject().setProperty(name, engine.newQObject(obj))

    def source_drag(name, rect, reverse=False):
        x, y, width, height = rect
        p1, p2 = ([x + width, y + height], [x, y]) if reverse else ([x, y], [x + width, y + height])
        return evaluate(f'''(function() {{
            const a = {name}.showImage.mapToItem({name}, {p1[0]}, {p1[1]});
            const b = {name}.showImage.mapToItem({name}, {p2[0]}, {p2[1]});
            const started = {name}.beginSelection(2, a.x, a.y);
            {name}.updateSelection(b.x, b.y);
            return started && {name}.finishSelection(2, b.x, b.y);
        }})()''')

    def assert_counts(count):
        app.processEvents()
        assert viewer.property("boundBoxCount") == count
        overlay = viewer.property("overlayLayer")
        counts = sorted(child.property("count") for child in overlay.children()
                        if child.metaObject().className().startswith("QQuickRepeater"))
        assert counts == [0, count], counts

    window = QQuickWindow()
    window.setTitle("Umi-OCR 当前源码忽略区域回归（合成事件，非系统手势验收）")
    window.resize(1000, 720)
    root.setParentItem(window.contentItem())
    window.show()
    wait_until(app, window.isExposed)

    with tempfile.TemporaryDirectory(prefix="umi-ignore-qml-") as temp:
        image = QImage(800, 400, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        image_paths = [Path(temp) / "page-one.png", Path(temp) / "page-two.png"]
        for path in image_paths:
            assert image.save(str(path), "PNG")
        urls = [QUrl.fromLocalFile(str(path)).toString() for path in image_paths]
        assert not evaluate("viewer.beginSelection(2, 100, 100)")
        assert not evaluate("viewer.finishSelection(2, 200, 200)")
        assert_counts(0)
        viewer.setSource(urls[0])
        wait_until(app, lambda: viewer.property("imageSW") == 800)
        assert evaluate("viewer.overlayLayer.parent === viewer.showImage")
        gesture_area = next(child for child in viewer.children()
                            if child.metaObject().className().startswith("QQuickMouseArea")
                            and getattr(child.property("acceptedButtons"), "value", child.property("acceptedButtons")) == 2)
        bind("gestureArea", gesture_area)
        flickable = next(child for child in viewer.children()
                         if child.metaObject().indexOfProperty("contentX") >= 0)
        bind("flickable", flickable)

        # fit、100%、放大与平移，正反向拖动都应回到同一原图矩形。
        expected = {"x": 300, "y": 120, "width": 120, "height": 80}
        geometry_cases = 0
        for scale, pan_x, pan_y in ((0.75, 0, 0), (1, 120, 0), (1.5, 300, 80), (2, 500, 120)):
            viewer.setProperty("scale", scale)
            flickable.setProperty("contentX", pan_x)
            flickable.setProperty("contentY", pan_y)
            app.processEvents()
            for reverse in (False, True):
                viewer.clearIg()
                evaluate("previousBoxes = viewer.ig1Boxes")
                assert source_drag("viewer", (300, 120, 120, 80), reverse)
                actual = evaluate("viewer.ig1Boxes[0]")
                assert all(abs(actual[key] - value) < 1e-6 for key, value in expected.items()), (scale, actual)
                assert evaluate("previousBoxes !== viewer.ig1Boxes && previousBoxes.length === 0")
                assert_counts(1)
                geometry_cases += 1
        assert source_drag("viewer", (320, 130, 50, 40))
        assert_counts(2)
        evaluate("previousBoxes = viewer.ig1Boxes")
        viewer.revokeIg()
        assert evaluate("previousBoxes !== viewer.ig1Boxes && previousBoxes.length === 2")
        assert_counts(1)
        viewer.clearIg()
        assert_counts(0)

        # 左键、无起点释放、取消/离开后释放、出画布和退化选区均不得提交。
        viewer.imageFullFit()
        assert not evaluate("viewer.beginSelection(1, 100, 100)")
        assert not evaluate("viewer.finishSelection(1, 200, 200)")
        assert not evaluate("viewer.finishSelection(2, 200, 200)")
        for signal in ("canceled", "exited"):
            assert evaluate("viewer.beginSelection(2, 100, 100)")
            evaluate(f"gestureArea.{signal}()")
            assert not viewer.property("drawingIgnore")
            assert not evaluate("viewer.finishSelection(2, 200, 200)")
        for end_x, end_y in ((-1, 200), (601, 200), (200, -1), (200, 401), (100, 100), (100.1, 100.1)):
            assert evaluate("viewer.beginSelection(2, 100, 100)")
            assert not evaluate(f"viewer.finishSelection(2, {end_x}, {end_y})")
        assert_counts(0)
        # 图片留白内的拖动裁剪到原图；完全处于留白则没有面积。
        assert evaluate("viewer.beginSelection(2, 0, 0) && viewer.finishSelection(2, 600, 400)")
        assert evaluate("viewer.getIgnoreArea()") == [[[0, 0], [800, 0], [800, 400], [0, 400]]]
        viewer.clearIg()
        assert evaluate("viewer.beginSelection(2, 20, 10)")
        assert not evaluate("viewer.finishSelection(2, 100, 20)")
        assert_counts(0)
        evaluate("viewer.ig1Boxes = [{x:10.5,y:20.5,width:789.5,height:379.5}]")
        assert evaluate("viewer.getIgnoreArea()") == [[[11, 21], [800, 21], [800, 400], [11, 400]]]
        viewer.clearIg()
        for action in ("viewer.visible = false", "viewer.clearIg()", "viewer.revokeIg()"):
            assert evaluate("viewer.beginSelection(2, 100, 100)")
            evaluate(action)
            assert not viewer.property("drawingIgnore")
            viewer.setVisible(True)
            assert not evaluate("viewer.finishSelection(2, 200, 200)")
        assert evaluate("viewer.beginSelection(2, 100, 100)")
        viewer.setSource(urls[1])
        wait_until(app, lambda: viewer.property("imageSW") == 800)
        assert not viewer.property("drawingIgnore")
        assert not evaluate("viewer.finishSelection(2, 200, 200)")
        assert_counts(0)

        # Qt 层合成事件只验证事件接线，不能代替真实 Windows 右鼠标手势。
        def mouse_event(kind, point, button, buttons):
            local = QPointF(*point)
            global_point = QPointF(window.mapToGlobal(local.toPoint()))
            event = QMouseEvent(kind, local, local, global_point, button, buttons, Qt.KeyboardModifier.NoModifier)
            QCoreApplication.sendEvent(window, event)

        mouse_event(QEvent.Type.MouseButtonPress, (180, 140), Qt.MouseButton.RightButton, Qt.MouseButton.RightButton)
        assert viewer.property("drawingIgnore")
        mouse_event(QEvent.Type.MouseMove, (300, 240), Qt.MouseButton.NoButton, Qt.MouseButton.RightButton)
        mouse_event(QEvent.Type.MouseButtonRelease, (300, 240), Qt.MouseButton.RightButton, Qt.MouseButton.NoButton)
        assert_counts(1)
        viewer.clearIg()
        viewer.setProperty("scale", 2)
        flickable.setProperty("contentX", 500)
        flickable.setProperty("contentY", 120)
        app.processEvents()
        pan_before = float(flickable.property("contentX"))
        mouse_event(QEvent.Type.MouseButtonPress, (200, 150), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        for x in (215, 235, 255, 275):
            mouse_event(QEvent.Type.MouseMove, (x, 150), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        mouse_event(QEvent.Type.MouseButtonRelease, (275, 150), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        assert_counts(0)
        assert not viewer.property("drawingIgnore")
        assert float(flickable.property("contentX")) < pan_before, (pan_before, flickable.property("contentX"))
        evaluate("flickable.cancelFlick()")

        # 实例化真实 PreviewDoc，仅替换文档/I/O 连接器；预览参数不能依赖先关闭面板。
        info = {"path": "受控文档.pdf", "page_count": 6, "range_start": 1, "range_end": 6,
                "password": "", "is_encrypted": False, "is_authenticate": True}
        preview.show(info)
        canvas = next(child for child in preview.findChildren(QQuickItem)
                      if child.metaObject().indexOfProperty("ig1Boxes") >= 0)
        bind("canvas", canvas)
        wait_until(app, lambda: canvas.property("imageSW") == 800)
        canvas.clearIg()
        assert source_drag("canvas", (100, 60, 120, 80))
        preview.setProperty("ignoreRangeStart", 2)
        preview.setProperty("ignoreRangeEnd", -2)
        ignore_config = evaluate("preview.getIgnoreConfig()")
        assert ignore_config["tbpu.ignoreArea"] == [[[100, 60], [220, 60], [220, 140], [100, 140]]]
        original_config = evaluate("Object.assign({}, root.configValues)")
        ocr_button = next(child for child in preview.findChildren(QObject)
                          if child.property("text_") == "OCR" and child.metaObject().indexOfProperty("checked") >= 0)
        ocr_button.setProperty("checked", True)
        preview.toPreview()
        connector = DocPreviewStub.instances[0]
        assert connector.ocr_calls
        argd = connector.ocr_calls[-1][3]
        assert {key: argd[key] for key in IGNORE_KEYS} == ignore_config
        assert argd["tbpu.parser"] == "None" and argd["unchanged"] == 42
        assert evaluate("root.configValues") == original_config

        # 使用当前源码的真实后处理单元，区域内文本删除，区域外/跨边界文本保留。
        module = importlib.import_module("py_src.ocr.tbpu.ignore_area")
        assert Path(module.__file__).resolve() == source_root / "py_src" / "ocr" / "tbpu" / "ignore_area.py"
        blocks = [
            {"text": "区域内", "box": [[110, 70], [150, 70], [150, 90], [110, 90]]},
            {"text": "区域外", "box": [[300, 70], [350, 70], [350, 90], [300, 90]]},
            {"text": "跨边界", "box": [[200, 70], [240, 70], [240, 90], [200, 90]]},
        ]
        filtered = module.IgnoreArea(argd["tbpu.ignoreArea"]).run(blocks)
        assert [block["text"] for block in filtered] == ["区域外", "跨边界"]
        connector.previewOcr.emit([info["path"], 1, {"code": 100, "data": filtered}])
        assert [block["text"] for block in evaluate("canvas.textBoxes")] == ["区域外", "跨边界"]

        assert evaluate("canvas.beginSelection(2, 100, 100)")
        preview.changePage(2, 0)
        assert not canvas.property("drawingIgnore")
        assert not evaluate("canvas.finishSelection(2, 200, 200)")
        assert evaluate("canvas.beginSelection(2, 100, 100)")
        preview.setVisible(False)
        assert not canvas.property("drawingIgnore")
        saved = evaluate("root.callbackInfo")
        assert saved["path"] == info["path"]
        assert saved["fields"]["page_count"] == 6
        assert saved["fields"]["argd"] == ignore_config
        assert {key: saved["configsAtCallback"][key] for key in IGNORE_KEYS} == ignore_config
        assert {key: evaluate("root.configValues")[key] for key in IGNORE_KEYS} == ignore_config
        assert connector.clear_count == 1
        preview.show(info)
        wait_until(app, lambda: canvas.property("imageSW") == 800)
        assert evaluate("canvas.getIgnoreArea()") == ignore_config["tbpu.ignoreArea"]
        canvas.clearIg()
        preview.toPreview()
        assert connector.ocr_calls[-1][3].get("tbpu.ignoreArea") is None
        preview.setVisible(False)
        assert evaluate("root.callbackInfo.fields.argd['tbpu.ignoreArea']") is None
        preview.show(info)
        assert evaluate("canvas.ig1Boxes.length") == 0
        ocr_button.setProperty("checked", False)
        preview.setVisible(False)

        # 图片忽略区域编辑器也复用同一格式，关闭/重开不复活草稿或旧数组。
        editor.showImgID("editor-page")
        image_editor = editor.property("imageWithIgnore")
        bind("imageEditor", image_editor)
        wait_until(app, lambda: image_editor.property("imageSW") == 800)
        assert source_drag("imageEditor", (100, 60, 120, 80), True)
        assert evaluate("imageEditor.beginSelection(2, 100, 100)")
        editor.setVisible(False)
        assert evaluate("root.configValues['tbpu.ignoreArea']") == ignore_config["tbpu.ignoreArea"]
        editor.showImgID("editor-page-reopened")
        image_editor = editor.property("imageWithIgnore")
        bind("imageEditor", image_editor)
        assert evaluate("imageEditor.getIgnoreArea()") == ignore_config["tbpu.ignoreArea"]
        image_editor.clearIg()
        editor.setVisible(False)
        editor.showImgID("editor-page-empty")
        bind("imageEditor", editor.property("imageWithIgnore"))
        assert evaluate("imageEditor.ig1Boxes.length") == 0
        editor.setVisible(False)

    assert not qml_errors, "\n".join(qml_errors[:20])
    window.close()
    root.setParentItem(None)
    root.deleteLater()
    component.deleteLater()
    window.deleteLater()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    qInstallMessageHandler(old_handler)
    del handles
    print(json.dumps({
        "result": "PASS", "python": sys.version.split()[0], "pyside6": PySide6.__version__,
        "source_root": str(source_root), "qml_source": "local-files-only; no app.zip/ui.rcc",
        "geometry_cases": geometry_cases, "preview_connector_race_cases": connector_races,
        "var_binding_and_repeater": "PASS",
        "left_pan_and_right_draw_synthetic_qt_events": "PASS",
        "cancel_exit_source_page_close_zero_and_clip": "PASS",
        "preview_save_reopen_and_real_ignore_filter": "PASS",
        "native_windows_mouse_gesture": "未验收，需主会话真实系统鼠标集成验证",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
