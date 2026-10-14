import argparse
import json
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def _wait_until(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError("QML image did not become ready.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--ocr-result", type=Path)
    parser.add_argument("--ocr-input", type=Path)
    parser.add_argument("--overlay-output", type=Path)
    args = parser.parse_args()
    for name in ("ocr_result", "ocr_input", "overlay_output"):
        if getattr(args, name):
            setattr(args, name, getattr(args, name).resolve())
    data_root = args.data_root.resolve()
    handles = configure_runtime(data_root)

    from PySide6.QtCore import QObject, Property, QUrl, Slot
    from PySide6.QtGui import QColor, QGuiApplication, QImage
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication.instance() or QGuiApplication(["image-viewer-qml-test"])
    engine = QQmlEngine()
    engine.addImportPath(str(data_root / "site-packages" / "PySide6" / "qml"))
    context = engine.rootContext()
    context.setContextProperty(
        "theme",
        {
            "bgColor": QColor("#ffffff"),
            "coverColor4": QColor("#55000000"),
            "subTextColor": QColor("#555555"),
            "textColor": QColor("#111111"),
            "specialBgColor": QColor("#eeeeee"),
            "specialTextColor": QColor("#1166cc"),
            "dataFontFamily": "Arial",
        },
    )
    context.setContextProperty(
        "size_",
        {
            "line": 24,
            "text": 14,
            "spacing": 8,
            "smallLine": 16,
            "btnRadius": 4,
            "panelRadius": 4,
        },
    )
    class ConfigsStub(QObject):
        @Slot(str, result=bool)
        def getValue(self, _key):
            return True

    class QmlAppStub(QObject):
        def __init__(self):
            super().__init__()
            self._global_configs = ConfigsStub(self)

        @Property(bool, constant=True)
        def enabledEffect(self):
            return False

        @Property(QObject, constant=True)
        def globalConfigs(self):
            return self._global_configs

    qml_app = QmlAppStub()
    context.setContextProperty("qmlapp", qml_app)

    widgets_dir = (data_root / "qt_res" / "qml" / "Widgets").as_uri()
    viewer_dir = (data_root / "qt_res" / "qml" / "Widgets" / "ImageViewer").as_uri()
    if (data_root / "ui.rcc").is_file():
        widgets_dir = "qrc:/qt_res/qml/Widgets"
        viewer_dir = widgets_dir + "/ImageViewer"
    component = QQmlComponent(engine)
    component.setData(
        f'''
import QtQuick
import "{widgets_dir}" as Widgets
import "{viewer_dir}" as Viewer
Item {{
    id: root
    width: 800
    height: 500
    Viewer.TextBox {{
        id: textBox
        objectName: "textBox"
        x: 20; y: 15; width: 160; height: 75
        points: [[20, 30], [170, 15], [180, 70], [30, 90]]
        text: "A deliberately long OCR line that must stay inside its polygon"
    }}
    Viewer.ImageScale {{
        id: viewer
        objectName: "viewer"
        x: 250; width: 400; height: 260
        overlayLayer: Item {{ objectName: "testOverlay" }}
        property bool overlayAttached: overlayLayer.parent === showImage
    }}
    Viewer.ImageWithText {{
        id: imageWithText
        objectName: "imageWithText"
        visible: false
        width: 200; height: 100
        property int sourceBoxCount: textBoxes.length
    }}
    Widgets.DoubleRowLayout {{
        id: splitLayout
        objectName: "splitLayout"
        y: 300; width: 800; height: 180
        initSplitterX: 0.35
        leftItem: Item {{}}
        rightItem: Item {{}}
    }}
}}
'''.encode(),
        QUrl("inline:image-viewer-test.qml"),
    )
    _wait_until(app, lambda: not component.isLoading())
    obj = component.create()
    if obj is None:
        details = component.errorString() or "\n".join(
            error.toString() for error in component.errors()
        )
        raise RuntimeError(f"QML status {component.status()}: {details}")
    text_box = obj.findChild(type(obj), "textBox")
    viewer = obj.findChild(type(obj), "viewer")
    image_with_text = obj.findChild(type(obj), "imageWithText")
    split_layout = obj.findChild(type(obj), "splitLayout")
    assert all((text_box, viewer, image_with_text, split_layout))
    assert viewer.property("overlayAttached") is True
    image_with_text.showTextBoxes(
        {
            "code": 100,
            "data": [
                {
                    "text": "Selectable OCR text",
                    "box": [[10, 10], [180, 15], [175, 70], [12, 65]],
                    "score": 0.99,
                }
            ],
        }
    )
    app.processEvents()
    assert image_with_text.property("sourceBoxCount") == 1

    original_size = (text_box.property("width"), text_box.property("height"))
    text_box.resetSize()
    app.processEvents()
    assert (text_box.property("width"), text_box.property("height")) == original_size
    assert text_box.containsPoint(obj, 100, 50)
    assert not text_box.containsPoint(obj, 24, 18)
    assert abs(text_box.property("textAngle")) > 1

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "zoom.png"
        image = QImage(800, 400, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        assert image.save(str(path), "PNG")
        viewer.setSource(QUrl.fromLocalFile(str(path)).toString())
        _wait_until(app, lambda: viewer.property("imageSW") == 800)
        before = viewer.imagePointAt(320, 100).toVariant()
        viewer.imageScaleAddSub(1, 0.2, 320, 100)
        app.processEvents()
        after = viewer.imagePointAt(320, 100).toVariant()
        assert abs(float(before[0]) - float(after[0])) < 0.01, (before, after)

    available = float(split_layout.property("splitterAvailableWidth"))
    split_layout.setProperty("splitterX", available * 0.37)
    app.processEvents()
    ratio = float(split_layout.property("splitterX")) / available
    split_layout.setProperty("width", 1200)
    _wait_until(
        app,
        lambda: abs(
            float(split_layout.property("splitterX"))
            / float(split_layout.property("splitterAvailableWidth"))
            - ratio
        )
        < 0.001,
    )

    if args.ocr_result:
        from PySide6.QtQuick import QQuickWindow
        result = json.loads(args.ocr_result.read_text("utf-8"))
        window = QQuickWindow()
        window.resize(960, 500)
        obj.setParentItem(window.contentItem())
        obj.setWidth(960)
        for child in (text_box, viewer, split_layout):
            child.setVisible(False)
        image_with_text.setVisible(True)
        image_with_text.setWidth(960)
        image_with_text.setHeight(500)
        image_with_text.setSource(QUrl.fromLocalFile(str(args.ocr_input.resolve())).toString())
        _wait_until(app, lambda: image_with_text.property("imageSW") > 0)
        image_with_text.showTextBoxes(result)
        app.processEvents()
        assert image_with_text.property("sourceBoxCount") == len(result["data"])
        engine.globalObject().setProperty("testViewer", engine.newQObject(image_with_text))
        for zoom in (0.5, 1.0, 1.04):
            image_with_text.setProperty("scale", zoom)
            app.processEvents()
            for i, block in enumerate(result["data"]):
                # Actual QML delegate center -> viewer -> image coordinates must match the model box.
                point = engine.evaluate(f"(function() {{ let b=testViewer.textBoxes[{i}]; let p=b.obj.mapToItem(testViewer,b.width/2,b.height/2); return testViewer.imagePointAt(p.x,p.y); }})()").toVariant()
                xs, ys = zip(*block.get("polygon", block["box"]))
                expected = [(min(xs)+max(xs))/2, (min(ys)+max(ys))/2]
                assert all(abs(x-y)<=1/zoom for x,y in zip(point,expected)), (zoom,point,expected)  # Qt centered anchors can round by a screen pixel.
        window.show()
        _wait_until(app, lambda: not window.grabWindow().isNull())
        if args.overlay_output:
            assert window.grabWindow().save(str(args.overlay_output.resolve()))
        window.close()
        window.deleteLater()

    obj.deleteLater()
    engine.deleteLater()
    app.processEvents()
    del handles
    print("Image viewer geometry, cursor zoom and proportional split tests passed.")


if __name__ == "__main__":
    main()
