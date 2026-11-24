"""在真实 Qt Quick WebEngine 验证离线富预览，不进行桌面捕获。"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--packaged", action="store_true", help="仅加载给定包内代码与资源，不注入仓库源码")
    args = parser.parse_args()
    data, work = args.data.resolve(), args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    os.chdir(work)
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    if os.environ.get("QTWEBENGINE_DISABLE_SANDBOX") or "--no-sandbox" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""):
        raise RuntimeError("验收不能关闭 Chromium 沙箱")
    module_root = data if args.packaged else ROOT / "UmiOCR-data"
    sys.path[:0] = [str(module_root), str(module_root / "py_src/imports"), str(module_root / "app.zip"), str(module_root / "app.zip/py_src/imports"), str(data / "site-packages"), str(data / "dependencies.zip")]
    handles = [os.add_dll_directory(str(data / "site-packages/PySide6"))]
    from PySide6.QtCore import QObject, Qt, QUrl, Slot, QCoreApplication, QEvent, QResource, QFile, QIODevice
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import qmlRegisterType
    from PySide6.QtQuick import QQuickView
    from PySide6.QtQuickControls2 import QQuickStyle
    from py_src.document.markdown_preview import initialize_preview, MarkdownPreviewConnector, _plain_file
    QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    initialize_preview()
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication([])
    qmlRegisterType(MarkdownPreviewConnector, "MarkdownPreviewConnector", 1, 0, "MarkdownPreviewConnector")
    view = QQuickView()
    view.setFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.resize(860, 680)
    engine = view.engine()
    engine.addImportPath(str(data / "site-packages/PySide6/qml"))
    context = engine.rootContext()
    context.setContextProperty("theme", {**{key: QColor(value) for key, value in {
        "bgColor": "#ffffff", "textColor": "#24292f", "subTextColor": "#57606a", "specialTextColor": "#0969da", "coverColor1": "#11000000", "coverColor2": "#22000000", "coverColor3": "#d0d7de", "coverColor4": "#55000000"}.items()}, "dataFontFamily": "Microsoft YaHei", "fontFamily": "Microsoft YaHei"})
    context.setContextProperty("size_", {"text": 16, "smallText": 13, "spacing": 8, "smallSpacing": 4, "line": 22, "smallLine": 18, "btnRadius": 4})
    context.setContextProperty("qmlapp", {"enabledEffect": False})
    class Observer(QObject):
        value = None
        @Slot("QVariant")
        def receive(self, value): self.value = value.toVariant() if hasattr(value, "toVariant") else value
    observer = Observer()
    engine.globalObject().setProperty("observer", engine.newQObject(observer))
    import py_src.document.markdown_preview as preview_module
    assert Path(preview_module.__file__).absolute().is_relative_to(module_root.absolute()), preview_module.__file__
    if args.packaged and (data / "ui.rcc").is_file():
        assert QResource.registerResource(str(data / "ui.rcc"))
        qml_path = ":/qt_res/qml/Widgets/DocumentMarkdownPreview.qml"
        qml_url = QUrl("qrc" + qml_path)
    else:
        qml_path = str(module_root / "qt_res/qml/Widgets/DocumentMarkdownPreview.qml")
        qml_url = QUrl.fromLocalFile(qml_path)
    assert preview_module._static_root(data / "app.zip/py_src/document/markdown_preview.py") == data / "qt_res/preview"
    assert preview_module._static_root(data / "py_src/document/markdown_preview.py") == data / "qt_res/preview"
    for relative in preview_module.STATIC:
        assert preview_module._read_static(relative), "实际布局缺少离线预览资源：" + relative
    view.setSource(qml_url)
    assert view.status() != QQuickView.Status.Error, view.errors()
    reader = view.rootObject()
    engine.globalObject().setProperty("reader", engine.newQObject(reader))
    view.show()
    def wait(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while not predicate():
            assert time.monotonic() < deadline, ("等待超时", reader.property("errorText"))
            app.processEvents()
            time.sleep(0.01)
    wait(lambda: reader.property("ready"))
    browser = reader.property("browser")
    assert browser is not None
    engine.globalObject().setProperty("web", engine.newQObject(browser))
    def js(expression):
        sentinel = object()
        observer.value = sentinel
        result = engine.evaluate("web.runJavaScript(" + json.dumps(expression) + ", function(value){observer.receive(value)})")
        assert not result.isError(), result.toString()
        wait(lambda: observer.value is not sentinel)
        return observer.value
    asset_root = work / "temp_doc/current-assets"
    asset_root.mkdir(parents=True)
    asset = asset_root / "图 一.png"
    from PIL import Image
    Image.new("RGB", (60, 40), "white").save(asset)
    private = work / "private.png"
    private.write_bytes(asset.read_bytes())
    source = """# 离线解析标题

公式 $x_1^2 + y_2$，以及 \\(a_b\\)。

$$
\\int_0^1 x^2 \\, dx = \\frac{1}{3}
$$

| 列一 | 列二 |
| --- | --- |
| 中文 | 123 |

```python
value = 42
print(value)
```

<div><img src="ASSET"><p>图片说明与 $c_d$</p></div>

非法公式 $\\unknowncommand{x}$ 后仍有文字。

<script>window.injected=1</script><iframe src="https://example.com"></iframe>
<img src="https://example.com/private" onerror="window.injected=2">
<a href="javascript:window.injected=3">危险链接</a>
<img src="PRIVATE"><div onclick="window.injected=4">安全保留文字</div>

传输边界：`</script>` 与中文、反引号及 U+2028：\u2028
""".replace("ASSET", asset.as_uri()).replace("PRIVATE", private.as_uri())
    reader.setProperty("resources", [{"path": str(asset), "uri": asset.as_uri()}, {"path": str(private), "uri": private.as_uri()}])
    reader.setProperty("text", source)
    wait(lambda: js("Boolean(window.umiPreview?.rendered && document.querySelector('h1'))"))
    dom = js("JSON.stringify({heading:document.querySelector('h1')?.textContent, formulas:document.querySelectorAll('.katex').length, errors:document.querySelectorAll('.katex-error').length, table:document.querySelectorAll('table').length, code:document.querySelector('pre code')?.textContent, highlighted:document.querySelectorAll('pre .hljs-number').length, gutter:document.querySelector('.code-lines')?.textContent, unsafe:document.querySelectorAll('script:not([src]),iframe,[onclick],[onerror],a[href^=javascript]').length, images:[...document.querySelectorAll('img[src]')].map(i=>({src:i.src,width:i.naturalWidth})), injected:window.injected||0, notice:document.querySelector('#notice').textContent, text:document.querySelector('#document').textContent})")
    dom = json.loads(dom)
    assert dom["heading"] == "离线解析标题", dom
    assert dom["formulas"] >= 4 and dom["errors"] >= 1, dom
    formula_sources = js("Array.from(document.querySelectorAll('annotation')).map(node => node.textContent)")
    assert "x_1^2 + y_2" in formula_sources and any(value.startswith(chr(92) + "int_0^1") for value in formula_sources), formula_sources
    assert dom["table"] == 1 and dom["highlighted"] > 0 and dom["gutter"] == "1\n2", dom
    assert dom["unsafe"] == 0 and dom["injected"] == 0, dom
    wait(lambda: js("Boolean(document.querySelector('img[src]')?.naturalWidth === 60)"))
    assert len(dom["images"]) == 1 and dom["images"][0]["src"].startswith("umi-preview://reader/assets/"), dom
    assert "未获授权" in dom["notice"] and "安全保留文字" in dom["text"], dom
    assert reader.property("text") == source
    assert engine.evaluate("web.controller.profile.offTheRecord").toBool()
    assert engine.evaluate("web.controller.profile.httpCacheType === 2").toBool()
    assert js("typeof window.qt === 'undefined'")
    rejected = False
    try: _plain_file(private, work / "temp_doc")
    except ValueError: rejected = True
    assert rejected
    checks = ["真实 WebEngine 渲染标题、HTML 图片、表格、代码高亮／行号、行内与块级公式，非法公式局部报错",
              "识别脚本、事件、iframe、javascript 链接和外部／未授权图片被阻止，原始 Markdown 未改变",
              "匿名 profile 无磁盘 HTTP 缓存，不关闭沙箱，不对页面暴露 Python bridge"]
    # 实际按钮驱动 WebEngine 缩放，而非临时修改 DOM 样式。
    for name, expected in (("markdownZoomIn", 1.1), ("markdownZoomReset", 1.0)):
        control = reader.findChild(QObject, name)
        assert control is not None
        engine.globalObject().setProperty("zoomControl", engine.newQObject(control))
        clicked = engine.evaluate("zoomControl.clicked()")
        assert not clicked.isError(), clicked.toString()
        wait(lambda: abs(browser.property("zoomFactor") - expected) < 0.001)
    checks.append("实际放大／重置按钮驱动 WebEngine 缩放")
    # 主题更新不替换文档，也不改原始内容。
    engine.evaluate('reader.presentation=Object.assign({},reader.presentation,{dark:true,background:"#171a1f",foreground:"#eeeeee"})')
    wait(lambda: js("document.documentElement.dataset.dark === 'true'"))
    assert js("getComputedStyle(document.body).backgroundColor") == "rgb(23, 26, 31)"
    # 超过 loadHtml 约 2 MiB 的内容通过分块脚本传输和分段渲染。
    long_source = ("普通段落内容。" * 100 + "\n\n") * 1200 + "\n\n# 长文尾部"
    assert len(long_source.encode("utf-8")) > 2 * 1024 * 1024
    reader.setProperty("text", long_source)
    wait(lambda: js("Boolean(window.umiPreview?.rendered && document.querySelector('#document')?.textContent.trim().endsWith('长文尾部'))"), 90)
    assert reader.property("text") == long_source
    js("window.scrollTo(0,document.body.scrollHeight); true")
    engine.evaluate("reader.resetScroll()")
    wait(lambda: js("window.scrollY === 0"))
    checks.append("浅深主题切换、超过 2 MiB 文档分段传输／渲染与滚动复位通过")
    def resource_bytes(relative):
        resource = QFile(":/qt_res/" + relative)
        if not resource.exists(): resource.setFileName(str(module_root / "qt_res" / relative))
        assert resource.open(QIODevice.OpenModeFlag.ReadOnly)
        content = bytes(resource.readAll()); resource.close(); return content
    report = {"status": "PASS", "mode": "packaged" if args.packaged else "source", "checks": checks, "runtime": str(data), "source": qml_path,
              "dom": {key: value for key, value in dom.items() if key != "text"}, "longDocumentBytes": len(long_source.encode("utf-8")),
              "desktopCapture": "NOT_RUN", "sandboxDisabled": False,
              "sourceSha256": {"qt_res/qml/Widgets/DocumentMarkdownPreview.qml": hashlib.sha256(resource_bytes("qml/Widgets/DocumentMarkdownPreview.qml")).hexdigest(),
                  "py_src/document/markdown_preview.py": hashlib.sha256(preview_module.__loader__.get_data(preview_module.__file__)).hexdigest(),
                  "qt_res/preview/render.js": hashlib.sha256(resource_bytes("preview/render.js")).hexdigest()}}
    (work / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "checks": checks}, ensure_ascii=False))
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    del handles


if __name__ == "__main__":
    main()
