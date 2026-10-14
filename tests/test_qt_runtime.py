import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    handles = configure_runtime(data_root)

    from PySide6.QtCore import QObject, QTranslator, QUrl
    from PySide6.QtGui import QImageReader
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication
    from py_src.utils import app_opengl

    app_opengl.initOpengl()
    QQuickStyle.setStyle("Basic")
    app = QApplication.instance() or QApplication(["qt-runtime-test"])
    app.setQuitOnLastWindowClosed(False)
    assert not app.quitOnLastWindowClosed()
    assert (
        QQuickWindow.graphicsApi()
        == QSGRendererInterface.GraphicsApi.Direct3D11
    )
    app.styleHints().setWheelScrollLines(max(app.styleHints().wheelScrollLines(), 8))
    assert app.styleHints().wheelScrollLines() >= 8
    engine = QQmlEngine()
    engine.addImportPath(str(data_root / "site-packages" / "PySide6" / "qml"))
    component = QQmlComponent(engine)
    merged = (data_root / "ui.rcc").is_file()
    tray_icon = data_root / "qt_res" / "images" / "icons" / "umiocr.ico"
    icon_uri = "qrc:/qt_res/images/icons/umiocr.ico" if merged else tray_icon.as_uri()
    component.setData(
        b"""
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs as Dialogs
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects as Effects
import Qt.labs.platform as Platform
import Qt.labs.qmlmodels as Labs
Item {
    Button { text: "test" }
    RowLayout { Item { Layout.fillWidth: true } }
    Dialogs.FileDialog { }
    Platform.SystemTrayIcon {
        objectName: "runtimeTray"
        visible: true
        icon.source: "__TRAY_ICON_URI__"
    }
    Labs.TableModel { Labs.TableModelColumn { display: "name" } }
    Effects.ColorOverlay { color: "red" }
}
""".replace(b"__TRAY_ICON_URI__", icon_uri.encode()),
        QUrl("inline:qt-runtime-test.qml"),
    )
    while component.isLoading():
        app.processEvents()
    obj = component.create()
    if obj is None:
        details = component.errorString() or "\n".join(
            error.toString() for error in component.errors()
        )
        raise RuntimeError(f"QML component status {component.status()}: {details}")
    tray = obj.findChild(QObject, "runtimeTray")
    assert tray is not None
    app.processEvents()
    assert tray.property("available")
    assert tray.property("visible")
    geometry = tray.property("geometry")
    if sys.platform == "win32":
        assert geometry.width() > 0 and geometry.height() > 0, geometry
    tray.setProperty("visible", False)
    app.processEvents()
    obj.deleteLater()

    image_formats = {bytes(value).decode().lower() for value in QImageReader.supportedImageFormats()}
    assert {"gif", "ico", "jpeg", "svg", "tiff", "webp"} <= image_formats
    for translation in (data_root / "i18n").glob("*.qm"):
        translator = QTranslator()
        assert translator.load(str(translation)), translation

    manifest = json.loads((data_root / "qt-runtime-whitelist.json").read_text("utf-8-sig"))
    pyside = data_root / "site-packages" / "PySide6"
    for name in manifest["pythonExtensions"]:
        assert (pyside / name).is_file(), name
    for relative in manifest["plugins"]:
        assert (pyside / "plugins" / relative).is_file(), relative
    for relative in manifest["qmlModules"]:
        assert (pyside / "qml" / relative / "qmldir").is_file(), relative
    assert not (pyside / "Qt6WebEngineCore.dll").exists()
    assert not (pyside / "opengl32sw.dll").exists()
    assert not (pyside / "qml" / "QtQuick" / "Controls" / "Material").exists()

    tray_qml = data_root / "qt_res" / "qml" / "MainWindow" / "SystemTray.qml"
    if merged:
        from PySide6.QtCore import QFile
        resource = QFile(":/qt_res/qml/MainWindow/SystemTray.qml")
        assert resource.open(QFile.ReadOnly)
        tray_source = bytes(resource.readAll()).decode("utf-8")
    else:
        tray_source = tray_qml.read_text("utf-8")
    assert "SystemTrayIcon" in tray_source
    assert "visible: true" in tray_source
    assert "visible: false" not in tray_source
    assert 'icon.source: Qt.resolvedUrl("../../images/icons/umiocr.ico")' in tray_source
    assert "Component.onDestruction" in tray_source
    assert "SystemTrayIcon.Trigger" in tray_source
    assert "SystemTrayIcon.DoubleClick" in tray_source
    assert "SystemTrayIcon.Context" in tray_source
    assert "trayMenu.open()" in tray_source
    assert "startScreenshot()" in tray_source
    assert "setVisibility(true)" in tray_source
    assert "左键单击：截屏" in tray_source
    icon = (tray_qml.parent / "../../images/icons/umiocr.ico").resolve()
    if merged: assert QFile.exists(":/qt_res/images/icons/umiocr.ico")
    else: assert icon.is_file(), icon

    if merged:
        import zipfile
        with zipfile.ZipFile(data_root / "app.zip") as archive:
            run_source = archive.read("py_src/run.py").decode("utf-8")
    else:
        run_source = (data_root / "py_src" / "run.py").read_text("utf-8")
    assert "from PySide6.QtWidgets import QApplication" in run_source
    assert "qtApp = QApplication(sys.argv)" in run_source
    assert "qtApp.setQuitOnLastWindowClosed(False)" in run_source

    engine.deleteLater()
    app.processEvents()
    print(
        f"Trimmed Qt runtime tests passed: {len(manifest['qmlModules'])} QML modules, "
        f"{len(manifest['rootDlls'])} root DLLs, {len(image_formats)} image formats."
    )
    del handles


if __name__ == "__main__":
    main()
