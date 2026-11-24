"""本轮设置与文档分页的真实 Windows Qt 源运行；仅操作自有窗口和新沙盒。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import sys
import time
import traceback
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "build/audit/ui-refinement-20261030-r1"
WORK = ROOT / "build/tmp/ui-refinement-20261030-r1"
RUNTIME = ROOT / "release/Umi-OCR/UmiOCR-data"
PLUGIN = Path(r"D:\Code\Python\Umi-OCR-Plugin\win32_PaddleOCRVL_1_6")
PP, VL = "win32_PaddleOCRv6_CUDA", "win32_PaddleOCRVL_1_6"
FORBIDDEN = {"paddle", "paddleocr", "paddlex", "torch", "onnxruntime", "transformers", "tensorrt"}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HELPER = load("ui_refinement_native_helpers", ROOT / "tests/test_settings_center_native_ui.py")
SCHEDULER = load("ui_refinement_native_scheduler", ROOT / "tests/test_hot_ui.py")
require, sha = HELPER.require, HELPER.sha256


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def prepare(sandbox, manifest):
    sandbox = HELPER.reject_links(sandbox)
    require(sandbox.parent == WORK and not sandbox.exists(), "只在本轮工作根准备全新沙盒")
    require(manifest.parent == AUDIT and not manifest.exists(), "只写本轮全新准备清单")
    sandbox.mkdir()
    data = sandbox / "UmiOCR-data"
    data.mkdir()
    originals, copies = {}, {}
    total = 0

    def copy(origin, target):
        nonlocal total
        HELPER.reject_links(origin)
        require(origin.is_file() and origin.stat().st_size < 32 * 1024 * 1024, "轻量源码输入异常：" + str(origin))
        digest = sha(origin)
        target.parent.mkdir(parents=True, exist_ok=True)
        require(not target.exists(), "不能覆盖沙盒输入")
        shutil.copy2(origin, target)
        require(sha(origin) == digest == sha(target), "复制期间输入变化")
        total += target.stat().st_size
        require(total < 128 * 1024 * 1024, "沙盒轻量输入超过预算")
        originals[str(origin)], copies[str(target)] = digest, digest

    for name in ("main.py", "about.json", "runtime_archive_bootstrap.py"):
        copy(ROOT / "UmiOCR-data" / name, data / name)
    for name in ("py_src", "qt_res", "i18n"):
        source = ROOT / "UmiOCR-data" / name
        for path in HELPER.source_files(source): copy(path, data / name / path.relative_to(source))
    plugin_inputs = {
        PP: (ROOT / "UmiOCR-data/plugins" / PP, ("__init__.py", "api.py", "config.py", "i18n_helpers.py", "i18n.csv", "umi-plugin.json")),
        VL: (PLUGIN, ("__init__.py", "api.py", "ocr_api.py", "checks.py", "asset_paths.py", "budgets.py", "runtime.py", "page.py", "StructuredDocument.qml", "i18n.csv", "umi-plugin.json", "runtime_archive_bootstrap.py")),
    }
    for key, (source, names) in plugin_inputs.items():
        for name in names: copy(source / name, data / "plugins" / key / name)
    copy(RUNTIME.parent / "Umi-OCR.exe", sandbox / "Umi-OCR.exe")
    copy(Path(__file__).resolve(), sandbox / "controller-inputs" / Path(__file__).name)
    for name in ("os-temp", "os-cache", "os-roaming", "os-local", "qt-cache", "fixtures", "exports"):
        (sandbox / name).mkdir()
    # 新生成的无敏感 PDF/图片，仅是读取预览输入；不调用模型或读取用户文档。
    sys.path[:0] = [str(RUNTIME / "site-packages"), str(RUNTIME / "dependencies.zip")]
    import fitz
    pdf = sandbox / "fixtures/three-pages.pdf"
    with fitz.open() as document:
        for index, color in enumerate(((0.96, 0.89, 0.80), (0.85, 0.96, 0.85), (0.83, 0.89, 0.98)), 1):
            page = document.new_page(width=420, height=600)
            page.draw_rect(page.rect, color=color, fill=color)
            page.insert_text((35, 80), f"PREVIEW FIXTURE - PAGE {index}", fontsize=22)
            page.insert_text((35, 125), "Visible before document parsing starts.", fontsize=13)
        document.save(str(pdf))
    image = sandbox / "fixtures/one-page.png"
    with fitz.open(pdf) as document: document[0].get_pixmap().save(str(image))
    fixtures = {str(path): sha(path) for path in (pdf, image)}
    dependencies = {str(RUNTIME / name): sha(RUNTIME / name) for name in ("runtime/python.exe", "runtime/python313.dll", "runtime/python313.zip",
        "site-packages/shiboken6/Shiboken.pyd", "site-packages/shiboken6/shiboken6.abi3.dll", "site-packages/PySide6/Qt6Core.dll",
        "site-packages/PySide6/Qt6Qml.dll", "site-packages/PySide6/Qt6Quick.dll", "site-packages/PySide6/plugins/platforms/qwindows.dll")}
    value = {"format": "ui-refinement-native-source-v1", "status": "PREPARED_NOT_RUN", "sandbox": str(sandbox),
        "runtime": str(RUNTIME), "source_inputs": originals, "snapshot_inputs": copies, "dependency_inputs": dependencies, "fixtures": fixtures,
        "copied_files": len(copies), "copied_bytes": total, "scope": "本轮源码真实Qt窗口；不覆盖release，不读取真实设置，不启动模型。逐页解析事件为受控回调，不是实际模型推理。"}
    write_new(manifest, value)
    print(json.dumps({"status": value["status"], "manifest": str(manifest), "files": len(copies), "bytes": total}, ensure_ascii=False))


def run_native(manifest_path, output):
    require(output.parent == AUDIT and not output.exists(), "使用新的本轮原生结果路径")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sandbox = HELPER.reject_links(Path(manifest["sandbox"]))
    require(sandbox.parent == WORK and manifest["format"] == "ui-refinement-native-source-v1", "源沙盒边界不符")
    data, packages = sandbox / "UmiOCR-data", RUNTIME / "site-packages"
    require(Path(sys.executable).resolve() == RUNTIME / "runtime/python.exe", "只借用指定便携Python")
    report = {"status": "RUNNING", "scope": manifest["scope"], "manifest": str(manifest_path), "manifestSha256": sha(manifest_path),
        "checks": [], "screenshots": [], "operations": [], "qt_problems": [], "errors": [], "scenario_completed": False,
        "normal_exit": False, "model_inference": "NOT_RUN", "real_clipboard": "NOT_READ_OR_CHANGED", "allowed_probe_processes": []}
    engines, processes, handles = [], [], []
    started = time.monotonic()
    original_engine = original_installer = original_popen = None
    finder = None
    try:
        for field in ("source_inputs", "snapshot_inputs", "dependency_inputs", "fixtures"):
            require(not HELPER.changed_inputs(manifest[field]), "准备输入已变化：" + field)
        for variable, name in (("TEMP", "os-temp"), ("TMP", "os-temp"), ("XDG_CACHE_HOME", "os-cache"),
                ("APPDATA", "os-roaming"), ("LOCALAPPDATA", "os-local"), ("QT_SHADER_CACHE_PATH", "qt-cache")):
            os.environ[variable] = str(sandbox / name)
        os.environ["QML_DISABLE_DISK_CACHE"] = "1"
        sys.path[:] = [entry for entry in sys.path if "app.zip" not in entry.lower()]
        sys.path[:0] = [str(packages), str(RUNTIME / "dependencies.zip")]
        handles.append(os.add_dll_directory(str(packages / "PySide6")))
        namespace = runpy.run_path(str(data / "main.py"), run_name="ui_refinement_source_entry")
        namespace["initRuntimeEnvironment"]()
        import site
        site.addsitedir(str(data / "py_src/imports"))
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(packages / "PySide6/plugins/platforms")
        from PySide6 import QtCore, QtQml
        from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, QSettings, QTimer, Qt, QUrl
        from PySide6.QtGui import QGuiApplication, QMouseEvent, QWheelEvent
        from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
        from PySide6.QtWidgets import QApplication
        import psutil
        import shiboken6
        QCoreApplication.setLibraryPaths([str(packages / "PySide6/plugins")])
        os.MessageBox = lambda message, *_args, **_kwargs: report["errors"].append("启动诊断：" + str(message))

        class NoInference(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in FORBIDDEN or fullname in {PP + ".worker", VL + ".worker"}:
                    raise RuntimeError("原生UI回归禁止推理模块：" + fullname)
        finder = NoInference()
        sys.meta_path.insert(0, finder)
        from py_src.utils import cuda_device_probe
        bootstrap = cuda_device_probe._WORKER_BOOTSTRAP
        import subprocess
        original_popen = subprocess.Popen
        class ProbeOnly(original_popen):
            def __init__(self, *args, **kwargs):
                argv = kwargs.get("args", args[0] if args else None)
                require(HELPER.trusted_probe(kwargs.get("executable"), argv, kwargs.get("cwd"), RUNTIME / "runtime/python.exe", data, bootstrap), "禁止非可信设备发现子进程")
                require(len(processes) < 40 and kwargs.get("shell", False) is False, "子进程预算/模式不符")
                super().__init__(*args, **kwargs)
                processes.append(self)
                report["allowed_probe_processes"].append({"pid": self.pid, "argv": argv, "cwd": str(kwargs.get("cwd"))})
        subprocess.Popen = ProbeOnly
        original_installer = QtCore.qInstallMessageHandler
        def install(handler):
            def observed(kind, context, text):
                if kind in (QtCore.QtMsgType.QtWarningMsg, QtCore.QtMsgType.QtCriticalMsg, QtCore.QtMsgType.QtFatalMsg):
                    counts = report.setdefault("qt_problem_counts", {})
                    counts[text] = counts.get(text, 0) + 1
                    if counts[text] == 1 and len(report["qt_problems"]) < 100:
                        report["qt_problems"].append({"kind": kind.name, "file": context.file, "line": context.line, "text": text})
                if handler: handler(kind, context, text)
            return original_installer(observed)
        QtCore.qInstallMessageHandler = install

        settings = QSettings(str(data / ".settings"), QSettings.IniFormat)
        require(not settings.allKeys(), "新沙盒不得已有用户配置")
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        initial = {"Global/server.enable": False, "Global/server.port": port, "Global/ocr.lifecycle.warmupMode": "lazy",
            "Global/ocr.lifecycle.cleanupPolicy": "never", "Global/ui.theme": "Default Light", "Global/window.simpleNotificationType": "none",
            "TabPageManager/openPageList": ["Navigation"], "TabPageManager/showPageIndex": 0,
            "ScreenshotOCR/hotkey.screenshot": "", "ScreenshotOCR/hotkey.paste": "", "ScreenshotOCR/hotkey.reScreenshot": ""}
        for key, value in initial.items(): settings.setValue(key, value)
        settings.sync()
        require(settings.status() == QSettings.NoError, "独立配置写入失败")
        del settings
        write_new(data / ".pre_settings", {"i18n": "zh_CN", "opengl": "", "server_port": port, "last_pid": -1, "last_ptime": -1})
        write_new(data / "plugins/.plugins_state", {})
        # 只替换外部剪贴板边界，避免回归测试改动用户真实剪贴板。
        from py_src.utils import utils
        utils.copyText = lambda text: report.setdefault("copied_text", []).append(text)
        original_engine = QtQml.QQmlApplicationEngine

        def evaluate(obj, code):
            expression = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
            value = expression.evaluate()
            require(not expression.hasError(), expression.error().toString())
            if isinstance(value, tuple): value = value[0]
            return value.toVariant() if hasattr(value, "toVariant") else value

        class Engine(original_engine):
            def load(self, *args):
                super().load(*args)
                engines.append(self)
                require(bool(self.rootObjects()), "没有真实应用窗口")
                window = self.rootObjects()[0]
                self.finished = self.begun = False
                self.kept = []
                def js(code, obj=window): return evaluate(obj, code)
                def jjson(code, obj=window): return json.loads(js("JSON.stringify(" + code + ")", obj))
                def wait(predicate, label, timeout=8):
                    yield from SCHEDULER.wait_transition(predicate, timeout=timeout, label=label)
                def walk(root):
                    pending = [root]
                    while pending:
                        item = pending.pop(0)
                        yield item
                        pending.extend(item.childItems())
                def exposed(item):
                    if item is None or not shiboken6.isValid(item) or not item.isVisible() or item.width() <= 0 or item.height() <= 0: return False
                    point = item.mapToScene(QPointF(item.width()/2, item.height()/2))
                    if not window.contentItem().boundingRect().contains(point): return False
                    ancestor = item
                    while ancestor is not None:
                        if not ancestor.isVisible() or ancestor.opacity() < .9: return False
                        if ancestor.clip() and not ancestor.boundingRect().contains(ancestor.mapFromScene(point)): return False
                        ancestor = ancestor.parentItem()
                    return True
                def click(item, label):
                    require(exposed(item) and item.isEnabled(), "真实控件不可点击：" + label)
                    local = item.mapToScene(QPointF(item.width()/2, item.height()/2))
                    global_point = item.mapToGlobal(QPointF(item.width()/2, item.height()/2))
                    for kind, button, buttons in ((QEvent.MouseMove, Qt.NoButton, Qt.NoButton), (QEvent.MouseButtonPress, Qt.LeftButton, Qt.LeftButton), (QEvent.MouseButtonRelease, Qt.LeftButton, Qt.NoButton)):
                        QCoreApplication.sendEvent(window, QMouseEvent(kind, local, global_point, button, buttons, Qt.NoModifier))
                    report["operations"].append({"label": label, "input": "QQuickWindow内鼠标事件", "point": [local.x(), local.y()]})
                def named(root, name):
                    item = root.findChild(QObject, name)
                    require(item is not None, "控件不存在：" + name)
                    return item
                def activate(key):
                    item = js("qmlapp.tab.openTabPageByKey(" + json.dumps(key) + ")")
                    require(item is not None, "页面不存在：" + key)
                    return item
                def capture(name):
                    image = window.grabWindow()
                    require(not image.isNull() and image.width() > 400, "应用窗口截图为空")
                    path = output.with_name(output.stem + "-" + name + ".png")
                    require(not path.exists() and image.save(str(path)), "截图失败/已存在")
                    report["screenshots"].append({"path": str(path), "sha256": sha(path), "width": image.width(), "height": image.height()})
                def stable():
                    return js("qmlapp.globalConfigs.applyPhase===0 && !qmlapp.globalConfigs.backendApplyPending && !qmlapp.globalConfigs.ocrManager.applying && !qmlapp.globalConfigs.documentManager.applying && !qmlapp.msnConnector.isBusy()")
                def global_set(key, value): js("qmlapp.globalConfigs.setValue(" + json.dumps(key) + "," + json.dumps(value, ensure_ascii=False) + ",true)")
                def finish(error=None):
                    if self.finished: return
                    self.finished = True
                    if error:
                        report["errors"].append("".join(traceback.format_exception(type(error), error, error.__traceback__)))
                        try: capture("failure")
                        except Exception as exc: report["errors"].append("失败截图：" + repr(exc))
                    QApplication.instance().quit()
                def choose(combo, index, label):
                    window.requestActivate()
                    yield 100
                    click(combo, label)
                    report.setdefault("combo_open_observations", []).append({"label": label, "class": combo.metaObject().className(),
                        "window_active": window.isActive(), "popup_visible": js("popup.visible", combo), "count": combo.property("count")})
                    yield from wait(lambda: js("popup.visible", combo), "下拉弹出")
                    yield from wait(lambda: exposed(js("popup.contentItem.itemAtIndex(" + str(index) + ")", combo)), "下拉项完成布局与淡入")
                    delegate = js("popup.contentItem.itemAtIndex(" + str(index) + ")", combo)
                    click(delegate, label + "选项")
                    yield from wait(lambda: not shiboken6.isValid(combo) or not js("popup.visible", combo), "下拉收起或模型重建旧控件")

                def scenario():
                    yield from wait(stable, "应用首帧初始化", 20)
                    require(js("size_.scale") == 1.25 and js("qmlapp.globalConfigs.getValue('ui.scale')") == 1.25, "125%默认未应用")
                    global_page = activate("GlobalConfigsPage")
                    yield 600
                    require(not js("qmlapp.globalConfigs.getValue('window.messageMemory').includes('globalConfigsKey')"), "不能预先写不再提示来掩盖弹窗")
                    visible_tips = [item for item in walk(window.contentItem()) if item.metaObject().indexOfProperty("text") >= 0 and item.property("text") == "小贴士" and exposed(item)]
                    require(not visible_tips, "仍自动弹小贴士")
                    require(not js("qmlapp.globalConfigs.compList.some(item=>item.sourceKey==='ocr.api'||item.key.indexOf('plugins.models.')===0)"), "全局仍显示模型或任务局部参数")
                    report["checks"].append("真实应用新设置默认为125%，全局设置不弹小贴士且不保留局部识别参数")
                    # 参数页控件确实位于各任务页；选择仍提交到唯一全局值。
                    pages = {}
                    for key in ("ScreenshotOCR", "BatchOCR", "BatchDOC"):
                        page = pages[key] = activate(key)
                        yield 250
                        require(js("configsComp.compList.some(item=>item.sourceKey==='ocr.api')", page), "任务页缺模型选择：" + key)
                        parameters = jjson("configsComp.compList.filter(item=>item.sourceKey && item.sourceKey.startsWith('ocr.') && item.sourceKey!=='ocr.api').map(item=>item.sourceKey)", page)
                        require(parameters, "任务页缺本地参数：" + key)
                        require(not js("Object.prototype.hasOwnProperty.call(configsComp.getValueDict(),'ocr.api')", page), "任务快照混入全局模型")
                    activate("ScreenshotOCR")
                    yield 250
                    model_item = js("configsComp.compList.find(item=>item.sourceKey==='ocr.api')", pages["ScreenshotOCR"])
                    combo = next(item for item in walk(model_item) if "ComboBox" in item.metaObject().className())
                    require(combo.property("count") >= 2, "真实源插件枚举不完整")
                    original_index = combo.property("currentIndex")
                    yield from choose(combo, 1 if original_index == 0 else 0, "切换共享OCR模型")
                    yield from wait(stable, "模型切换应用")
                    selected = js("qmlapp.globalConfigs.getValue('ocr.api')")
                    for page in pages.values():
                        require(js("configsComp.compList.find(item=>item.sourceKey==='ocr.api').value()", page) == selected, "模型入口未同步")
                    activate("ScreenshotOCR")
                    yield 150
                    model_item = js("configsComp.compList.find(item=>item.sourceKey==='ocr.api')", pages["ScreenshotOCR"])
                    combo = next(item for item in walk(model_item) if "ComboBox" in item.metaObject().className())
                    yield from choose(combo, original_index, "恢复共享OCR模型")
                    yield from wait(stable, "恢复模型应用")
                    def ocr_groups():
                        return jjson('(()=>{const c=configsComp; const groups=c.panelComponent.activeGroupItems(); const parent=groups[0].parent; return {layout:c.panelLayout.map(item=>item.key),registered:groups.map(item=>item.key),actual:Array.from(parent.children).filter(item=>item.key!==undefined).map(item=>({key:item.key,visible:item.visible,height:item.height,y:item.y,registered:groups.includes(item)}))}})()', pages["ScreenshotOCR"])
                    expected_groups = ["ocr", "tbpu", "hotkey", "action", "other"]
                    report["ocr_groups_before_settle"] = ocr_groups()
                    require(not any(item["visible"] and not item["registered"] for item in report["ocr_groups_before_settle"]["actual"]), "延迟销毁的旧设置组仍可见")
                    def ocr_layout_ready():
                        items = ocr_groups()["actual"]
                        return [item["key"] for item in items] == expected_groups and all(items[i+1]["y"] >= items[i]["y"]+items[i]["height"]-1 for i in range(len(items)-1))
                    yield from wait(ocr_layout_ready, "旧设置组回收及新组布局完成")
                    report["ocr_groups_after_settle"] = ocr_groups()
                    # 移开本窗口内的指针，不让设置行提示遮住代表性截图。
                    QCoreApplication.sendEvent(window, QMouseEvent(QEvent.MouseMove, QPointF(5,5), window.mapToGlobal(QPointF(5,5)), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
                    yield 100
                    capture("ocr-settings-125")
                    require(report["ocr_groups_after_settle"]["layout"] == expected_groups, "截图OCR布局描述含重复分组")
                    require(report["ocr_groups_after_settle"]["registered"] == expected_groups, "截图OCR活动分组重复")
                    require([item["key"] for item in report["ocr_groups_after_settle"]["actual"]] == expected_groups, "截图OCR视图残留未登记的旧分组")
                    report["checks"].append("三个OCR页面展示模型和所属参数，真实下拉点击同步全局模型，快照不混入全局项")

                    document = activate("StructuredDocument")
                    yield 300
                    capture("document-empty")
                    pdf, image = sandbox / "fixtures/three-pages.pdf", sandbox / "fixtures/one-page.png"
                    js("addPaths(" + json.dumps([str(pdf), str(image)]) + ")", document)
                    preview = named(document, "structuredPagePreview")
                    yield from wait(lambda: js("pageCount===3 && !previewLoading", document) and preview.property("imageSW") > 0, "真实三页PDF原始预览")
                    require(not js("parsing", document) and not jjson("Object.keys(documentResults)", document), "原始预览不能启动解析")
                    for expected in (2, 3):
                        click(named(document, "previewNext"), "解析前翻到第" + str(expected) + "页")
                        yield from wait(lambda: js("currentPage", document) == expected and not js("previewLoading", document), "真实原始页面切换")
                    require(preview.property("imageSW") == 420 and preview.property("imageSH") == 600, "原始页面尺寸不符")
                    capture("document-page3-before-parsing")
                    yield from choose(named(document, "structuredDocumentSelector"), 1, "切换预览到图片")
                    yield from wait(lambda: js("currentPath", document) == str(image) and js("pageCount===1 && !previewLoading", document), "图片独立页数")
                    yield from choose(named(document, "structuredDocumentSelector"), 0, "切回三页PDF")
                    yield from wait(lambda: js("currentPath", document) == str(pdf) and js("pageCount===3 && !previewLoading", document), "PDF独立页数")
                    js("setCurrentPage(3)", document)
                    yield from wait(lambda: not js("previewLoading", document), "恢复第3页")
                    report["checks"].append("真实三页PDF未解析即可浏览1/2/3页，图片与PDF切换保留各自实际页数")

                    # 真实页面控制器 + 本轮受控任务适配器；从不调用模型API。
                    controller_class = None
                    for module_name, module in list(sys.modules.items()):
                        candidate = getattr(module, "StructuredDocumentPage", None)
                        if candidate and str(getattr(module, "__file__", "")).replace("\\", "/").endswith("/" + VL + "/page.py"):
                            controller_class = candidate
                            break
                    require(controller_class is not None, "实际页面控制器来源不存在")
                    class ControlledMission:
                        jobs = []
                        cancelled = []
                        def addMissionList(self, info, paths):
                            self.jobs.append((info, paths))
                            return info["_reserved_msnID"]
                        def stopMissionList(self, mission_id): self.cancelled.append(mission_id)
                    controlled = ControlledMission()
                    controller_class._missionDocument = staticmethod(lambda: controlled)
                    click(named(document, "structuredRunCancel"), "通过真实页面控制器开始受控解析")
                    yield from wait(lambda: len(controlled.jobs) == 1 and js("parsing", document), "本页任务接纳")
                    info, paths = controlled.jobs[-1]
                    info["onStart"](info)
                    def page_result(number, final=False):
                        blocks = [{"id": str(i), "globalId": str(number) + ":" + str(i), "order": i, "categoryName": "Text", "category": "text",
                            "content": f"PAGE {number} BLOCK {i} " + "long-content-" * 35,
                            "bbox": [[20, 150+i*2], [350, 150+i*2], [350, 175+i*2], [20, 175+i*2]]} for i in range(100)]
                        return {"page": number, "text": (f"{'FINAL' if final else 'PARTIAL'} PAGE {number}\n" + "A scrollable line of document text.\n" * 150 + "BOTTOM_SENTINEL"),
                            "markdown": "# Page " + str(number) + "\n" + "Markdown line\n" * 150 + "MD_BOTTOM_SENTINEL", "blocks": blocks}
                    for number in (1, 2):
                        info["onPartial"]({"path": str(pdf), "page": number, "completedPages": number, "totalPages": 3,
                            "result": {"code": 100, "data": {"pages": [page_result(number)], "assets": []}}})
                        yield 100
                    require(js("currentPage", document) == 3 and js("pageCount", document) == 3, "逐页结果抢占浏览页/覆盖原始页数")
                    click(named(document, "resultPrevious"), "结果区翻到第二页")
                    yield 200
                    require(js("resultText(0).startsWith('PARTIAL PAGE 2')", document), "整篇完成前的第2页结果不可查看")
                    # 真实视口滚轮，不以只读内部值代替滚动。
                    text_scroll = named(document, "structuredTextScroll")
                    require(exposed(text_scroll), "文本滚动视口不可见")
                    for _ in range(8):
                        point = text_scroll.mapToScene(QPointF(text_scroll.width()/2, text_scroll.height()/2))
                        QCoreApplication.sendEvent(window, QWheelEvent(point, text_scroll.mapToGlobal(QPointF(text_scroll.width()/2,text_scroll.height()/2)), QPoint(0,0), QPoint(0,-1200), Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False))
                        yield 25
                    text_geometry = jjson("({y:contentItem.contentY,height:contentItem.contentHeight,view:height})", text_scroll)
                    require(text_geometry["y"] > 0 and text_geometry["height"] > text_geometry["view"], "长文本不能滚动")
                    js("contentItem.contentY=Math.max(0,contentItem.contentHeight-contentItem.height)", text_scroll)
                    yield 100
                    report["text_scroll_geometry"] = jjson("({y:contentItem.contentY,height:contentItem.contentHeight,view:height})", text_scroll)
                    capture("document-text-bottom")
                    js("resultTab=2", document)
                    json_scroll = named(document, "structuredJsonScroll")
                    result_tabs = named(document, "structuredResultTabs")
                    yield from wait(lambda: exposed(json_scroll) and abs(json_scroll.mapToScene(QPointF(0,0)).x()-result_tabs.mapToScene(QPointF(0,0)).x()) < .5, "JSON标签完成滑动")
                    geometry = jjson("({width:contentItem.contentWidth,height:contentItem.contentHeight,viewW:width,viewH:height})", json_scroll)
                    require(geometry["width"] > geometry["viewW"] and geometry["height"] > geometry["viewH"], "JSON没有双向滚动范围")
                    json_content = named(document, "structuredJsonContent")
                    require(js("contentItem.contentX===0 && contentItem.contentY===0", json_scroll), "JSON切换后未复位滚动位置")
                    yield 100
                    capture("document-json-start")
                    # 短坐标行在横向右移后可以完全离开视口；分别检查两方向，避免把正常裁切误判为丢字。
                    category_rect = jjson('(()=>{const r=positionToRectangle(text.indexOf("\\\"category\\\"")); return {x:r.x,y:r.y,height:r.height}})()', json_content)
                    js("contentItem.contentY=" + str(category_rect["y"]), json_scroll)
                    yield 100
                    require(js("contentItem.contentX===0 && contentItem.contentY>0", json_scroll), "JSON纵向滚动异常")
                    capture("document-json-vertical")
                    js("contentItem.contentX=30", json_scroll)
                    yield 100
                    require(js("contentItem.contentX>0 && contentItem.contentY>0", json_scroll), "JSON无法双向滚动")
                    category_point = json_content.mapToItem(json_scroll, QPointF(category_rect["x"], category_rect["y"]))
                    require(0 <= category_point.x() < json_scroll.width() and 0 <= category_point.y() < json_scroll.height(), "JSON目标字段没有出现在真实视口")
                    report["json_visible_category"] = {"x": category_point.x(), "y": category_point.y(), "height": category_rect["height"]}
                    report["json_scroll_geometry"] = jjson("({x:contentItem.contentX,y:contentItem.contentY,width:contentItem.contentWidth,height:contentItem.contentHeight,viewW:width,viewH:height,originX:contentItem.originX,originY:contentItem.originY})", json_scroll)
                    report["json_text_geometry"] = jjson('(()=>{const first=positionToRectangle(0); const block=positionToRectangle(text.indexOf("\\\"blocks\\\"")); return {x:x,y:y,width:width,height:height,implicitWidth:implicitWidth,implicitHeight:implicitHeight,contentWidth:contentWidth,contentHeight:contentHeight,topPadding:topPadding,verticalAlignment:verticalAlignment,first:[first.x,first.y,first.width,first.height],block:[block.x,block.y,block.width,block.height]}})()', json_content)
                    report["json_parent_geometry"] = [{"class": item.metaObject().className(), "x": item.x(), "y": item.y(), "width": item.width(), "height": item.height()} for item in (json_content, json_content.parentItem(), json_content.parentItem().parentItem(), json_scroll)]
                    capture("document-json-scroll")
                    js("resultTab=3", document)
                    blocks = named(document, "structuredBlocks")
                    yield from wait(lambda: exposed(blocks) and abs(blocks.mapToScene(QPointF(0,0)).x()-result_tabs.mapToScene(QPointF(0,0)).x()) < .5, "结构块标签完成滑动")
                    require(blocks.property("count") == 100, "结构块模型没有匹配当前页")
                    js("positionViewAtEnd()", blocks)
                    yield from wait(lambda: exposed(js("itemAtIndex(99)", blocks)), "末尾结构块可见")
                    require(blocks.property("contentY") > 0, "结构块不能滚动到末尾")
                    click(js("itemAtIndex(99)", blocks), "选中末尾结构块联动区域")
                    require(js("selectedBlockKey", document) == "2:2:99", "结构块点击未联动页面区域")
                    yield 100
                    report["block_scroll_geometry"] = jjson("({y:contentY,height:contentHeight,view:height,count:count})", blocks)
                    capture("document-blocks-scroll")
                    info["onPartial"]({"path": str(pdf), "page": 3, "failed": True, "warnings": ["CONTROLLED_PAGE_FAILURE"], "completedPages": 2, "totalPages": 3})
                    yield 100
                    click(named(document, "resultNext"), "结果区翻到失败页")
                    yield 150
                    require(js("resultStatus().includes('CONTROLLED_PAGE_FAILURE')", document), "失败页状态不可见")
                    click(named(document, "structuredRunCancel"), "取消受控解析")
                    yield 100
                    require(controlled.cancelled == [info["_reserved_msnID"]], "取消没有限定本页任务")
                    info["onEnd"](info, "[Warning] controlled cancellation")
                    yield 150
                    require(not js("parsing", document) and js("documentResults[currentPath].partial", document), "取消丢失完成页")
                    report["checks"].append("真实窗口中逐页结果提前可见，文本滚轮/JSON双向/结构块到底部有效，失败页和本页取消保留结果")
                    # 下一批最终结果只更新对应文档，不强制跳回第一页。
                    click(named(document, "structuredRunCancel"), "开始最终结果接线场景")
                    yield 100
                    final_info = controlled.jobs[-1][0]
                    final_result = {"code": 100, "text": "FULL_FINAL", "markdown": "# FULL_FINAL", "data": {"pages": [page_result(1,True),page_result(2,True),page_result(3,True)], "assets": []},
                        "metadata": {"sourceStem": "native-fixture", "pageCount": 3, "blockCount": 300}}
                    final_info["onGet"](final_info, {"path": str(pdf)}, final_result)
                    final_info["onEnd"](final_info, "[Success]")
                    yield 200
                    require(js("currentPage===3 && currentResultPage.text.startsWith('FINAL PAGE 3')", document), "最终结果改变浏览页或未替换逐页结果")
                    js("resultTab=0; wholeDocument=true", document)
                    yield 100
                    click(named(document, "structuredCopy"), "复制整篇结果到受控剪贴板边界")
                    require(report.get("copied_text", [])[-1] == "FULL_FINAL", "复制不是当前范围")
                    # 目录选择的 accepted 边界使用本轮已存在的新空目录，实际执行原控制器导出。
                    js("exportDialog.fileUrls_=[" + json.dumps(str(sandbox / "exports")) + "]; exportDialog.accepted()", document)
                    require(all((sandbox / "exports" / ("native-fixture." + suffix)).is_file() for suffix in ("txt", "md", "json")), "真实控制器导出缺件")
                    report["checks"].append("最终结果替换临时页但不抢页，整篇复制内容正确，真实控制器向自有目录导出TXT/Markdown/JSON")

                    # 通用Tooltip真实组件：窄窗、长无空格URL、不同缩放和主题。
                    activate("GlobalConfigsPage")
                    yield 200
                    tooltip_component = QQmlComponent(self, QUrl.fromLocalFile(str(data / "qt_res/qml/Widgets/ToolTip_.qml")))
                    tooltip = tooltip_component.create(QQmlEngine.contextForObject(window))
                    require(tooltip is not None, tooltip_component.errorString())
                    tooltip.setProperty("parent", window.contentItem())
                    self.kept.extend([tooltip_component, tooltip])
                    matrix = []
                    for theme_name in ("Default Light", "Neutral Dark"):
                        global_set("ui.theme", theme_name)
                        yield 100
                        for scale in (1.0, 1.25, 1.5):
                            global_set("ui.scale", scale)
                            for width in (760, 1240):
                                window.setWidth(width)
                                tooltip.setProperty("text", "https://example.invalid/" + "VeryLongModelFilenameWithoutSpaces" * 12 + "\n" + "长提示自动换行。" * 12)
                                tooltip.open()
                                yield from wait(lambda: bool(tooltip.property("visible")) and tooltip.property("opacity") > .99, "提示框实际可见")
                                content = tooltip.property("contentItem")
                                actual_width = tooltip.property("width")
                                require(actual_width <= min(480*scale, window.width()-2*js("size_.spacing")) + 1, "提示超过最大/窗口宽度")
                                require(content.property("lineCount") > 1 and tooltip.property("height") >= content.property("implicitHeight"), "长提示不换行或高度裁切")
                                matrix.append({"theme": theme_name, "scale": scale, "window_width": window.width(), "tooltip_width": actual_width, "lines": content.property("lineCount")})
                                tooltip.close()
                                yield from wait(lambda: not tooltip.property("visible"), "提示框关闭")
                    global_set("ui.theme", "Default Light")
                    global_set("ui.scale", 1.25)
                    window.setWidth(1300)
                    yield 200
                    tooltip.setProperty("text", "短提示")
                    tooltip.open()
                    yield from wait(lambda: bool(tooltip.property("visible")) and tooltip.property("opacity") > .99, "短提示可见")
                    require(tooltip.property("width") < 200, "短提示被强制撑满最大宽")
                    tooltip.close()
                    yield from wait(lambda: not tooltip.property("visible"), "短提示关闭")
                    # 代表性截图使用真正模型文件设置行的悬停，不只拍测试组件。
                    model_path_item = js("qmlapp.globalConfigs.compList.find(item=>item.origin && item.origin.type==='file' && String(item.origin.toolTip||'').includes('huggingface.co'))")
                    require(model_path_item is not None, "缺少模型文件提示行")
                    viewport = js("qmlapp.globalConfigs.panelComponent.contentItem")
                    point = model_path_item.mapToItem(viewport.property("contentItem"), QPointF(0,0))
                    viewport.setProperty("contentY", min(max(0, viewport.property("contentHeight")-viewport.height()), max(0, point.y()-viewport.height()*.4)))
                    yield 150
                    local = model_path_item.mapToScene(QPointF(model_path_item.width()*.2, model_path_item.height()/2))
                    global_point = model_path_item.mapToGlobal(QPointF(model_path_item.width()*.2, model_path_item.height()/2))
                    QCoreApplication.sendEvent(window, QMouseEvent(QEvent.MouseMove, local, global_point, Qt.NoButton, Qt.NoButton, Qt.NoModifier))
                    def real_tooltip():
                        return next((item for item in model_path_item.findChildren(QObject)
                            if item.metaObject().indexOfProperty('timeout') >= 0 and item.metaObject().indexOfProperty('delay') >= 0
                            and item.property('visible') and item.property('opacity') > .99), None)
                    yield from wait(lambda: real_tooltip() is not None, "真实模型文件行悬浮提示")
                    actual_tip = real_tooltip()
                    require(actual_tip.property("width") <= 600 and actual_tip.property("contentItem").property("lineCount") > 1, "实际文件提示未限宽换行")
                    report["actual_model_tooltip"] = {"text": actual_tip.property("text"), "width": actual_tip.property("width"),
                        "height": actual_tip.property("height"), "lines": actual_tip.property("contentItem").property("lineCount")}
                    capture("tooltip-wrapped-125")
                    QCoreApplication.sendEvent(window, QMouseEvent(QEvent.MouseMove, QPointF(5,5), window.mapToGlobal(QPointF(5,5)), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
                    report["tooltip_matrix"] = matrix
                    report["checks"].append("通用提示在双主题/100%/125%/150%/窄宽窗口限宽换行，长URL不断字丢失，短提示保持自然宽度")
                    activate("StructuredDocument")
                    yield 150
                    for language in ("en_US", "ja_JP", "pt", "ru_RU", "ta", "zh_TW", "zh_CN"):
                        global_set("ui.i18n", language)
                        yield from wait(lambda: stable() and js("qmlapp.globalConfigs.getValue('ui.i18n')") == language, "热切语言" + language)
                        yield 150
                        require(named(document, "structuredResultScope").property("count") == 2, "热切语言破坏结果范围")
                    capture("document-final-125")
                    report["checks"].append("文档解析页在七语热切后保留页码、范围与结果控件")
                    require(not any(name.split(".")[0] in FORBIDDEN for name in sys.modules), "误导入推理模块")
                    yield from wait(lambda: not cuda_device_probe._INFLIGHT, "自有设备发现回收", 15)
                    require(all(process.poll() is not None for process in processes), "设备发现子进程未退出")
                    require(not psutil.Process().children(recursive=True), "存在本轮未回收子进程")
                    require(not [connection for connection in psutil.Process().net_connections(kind="inet") if connection.status == psutil.CONN_LISTEN], "禁用HTTP仍有监听")
                    for field in ("source_inputs", "snapshot_inputs", "dependency_inputs", "fixtures"):
                        require(not HELPER.changed_inputs(manifest[field]), "验收期间输入被改动：" + field)
                    business_sources = {name: str(module.__file__) for name, module in sys.modules.items() if name.startswith("py_src.") and getattr(module, "__file__", None)}
                    require(all(Path(path).is_relative_to(data) for path in business_sources.values()), "业务模块来源混入旧应用")
                    report["business_module_sources"] = business_sources
                    report["checks"].append("业务模块来自新源沙盒，输入未变，无推理/服务监听/残留子进程，未读取或改变真实剪贴板")
                    report["scenario_completed"] = True

                def begin():
                    if self.begun: return
                    self.begun = True
                    self.steps = scenario()
                    SCHEDULER.start_steps(self.steps, QTimer.singleShot, lambda: finish(), finish)
                available = window.screen().availableGeometry()
                window.setWidth(min(1300, available.width()-80))
                window.setHeight(min(960, available.height()-100))
                window.frameSwapped.connect(lambda: QTimer.singleShot(0, begin) if not self.begun else None)
                window.show()
                window.requestActivate()
                QTimer.singleShot(20000, lambda: finish(AssertionError("没有应用首帧")) if not self.begun else None)
                QTimer.singleShot(180000, lambda: finish(AssertionError("原生场景超过有限时间预算")) if not self.finished else None)

        QtQml.QQmlApplicationEngine = Engine
        from py_src.run import main as run_application
        sys.argv = [str(sandbox / "Umi-OCR.exe"), "--force"]
        try:
            run_application(str(sandbox / "Umi-OCR.exe"), str(packages / "PySide6/qml"))
        except SystemExit as exc:
            require(exc.code in (None, 0), "应用异常退出：" + str(exc.code))
        report["normal_exit"] = bool(engines and all(engine.finished for engine in engines))
    except Exception:
        report["errors"].append(traceback.format_exc())
    finally:
        if "cuda_device_probe" in locals():
            with cuda_device_probe._CACHE_LOCK: pending = list(cuda_device_probe._INFLIGHT.values())
            for future in pending:
                try: future.result(timeout=12)
                except Exception as exc: report["errors"].append("设备发现收尾：" + repr(exc))
        for process in processes:
            try: process.wait(timeout=12)
            except Exception as exc: report["errors"].append("子进程收尾：" + repr(exc))
        if original_engine is not None: QtQml.QQmlApplicationEngine = original_engine
        if original_installer is not None: QtCore.qInstallMessageHandler = original_installer
        if original_popen is not None: subprocess.Popen = original_popen
        if finder is not None and finder in sys.meta_path: sys.meta_path.remove(finder)
        if "QApplication" in locals() and QApplication.instance():
            for engine in engines: engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            shiboken6.delete(QApplication.instance())
        report["elapsed_seconds"] = round(time.monotonic()-started, 3)
        report["status"] = "PASS" if report["scenario_completed"] and report["normal_exit"] and not report["errors"] and not report["qt_problems"] else "FAIL"
        write_new(output, report)
        print(json.dumps({"status": report["status"], "checks": report["checks"], "errors": report["errors"], "qt_problems": report["qt_problems"][:15], "screenshots": report["screenshots"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--sandbox", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "prepare": prepare(args.sandbox.resolve(), args.manifest.resolve())
    else: raise SystemExit(run_native(args.manifest.resolve(), args.output.resolve()))
