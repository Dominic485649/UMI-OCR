"""工作台／设置导航的真实 Windows 窗口验收；仅操作全新沙盒和自有窗口。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.util
import itertools
import json
import os
from pathlib import Path
import runpy
import socket
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("zh_CN", "en_US", "ja_JP", "pt", "ru_RU", "ta", "zh_TW")
THEMES = ("Default Light", "Neutral Dark")
FORBIDDEN = {"paddle", "paddleocr", "paddlex", "torch", "onnxruntime", "transformers", "tensorrt", "cupy"}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load("workbench_source_preparation", ROOT / "tests/test_ui_refinement_native.py")
HELPER, SCHEDULER = BASE.HELPER, BASE.SCHEDULER
require, sha = HELPER.require, HELPER.sha256


def write_new(path, value):
    path = Path(path)
    require(path.parent.is_dir() and not path.exists(), "结果必须使用既存目录下的新路径")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def prepare(args):
    work, audit, runtime = map(HELPER.reject_links, (args.work_root, args.audit_root, args.runtime_data))
    require(work.parent == ROOT / "build/tmp" and audit.is_relative_to(ROOT / "build/audit"), "本项目独立工作根")
    require(work.is_dir() and audit.is_dir(), "须先核实并建立工作根")
    BASE.WORK, BASE.AUDIT, BASE.RUNTIME = work, audit, runtime
    # 只读取已安装插件的公开适配层，不访问兄弟项目或模型。
    BASE.PLUGIN = runtime / "plugins" / BASE.VL
    BASE.prepare(work / args.name, audit / (args.name + "-source-inputs.json"))


def run(args):
    manifest_path, output = map(HELPER.reject_links, (args.manifest, args.output))
    require(manifest_path.is_file() and not output.exists() and output.parent.is_dir(), "输入清单存在、输出全新")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    root = HELPER.reject_links(Path(manifest["sandbox"]))
    runtime = HELPER.reject_links(Path(manifest["runtime"]))
    require(root.is_relative_to(ROOT / "build/tmp") and runtime.is_relative_to(ROOT), "只接纳项目内隔离程序")
    require(Path(sys.executable).resolve() == runtime / "runtime/python.exe", "必须使用声明的便携 Python")
    require(sys.flags.isolated and sys.flags.dont_write_bytecode, "隔离解释器、不写字节码")
    for field in ("source_inputs", "snapshot_inputs", "dependency_inputs", "fixtures"):
        require(not HELPER.changed_inputs(manifest.get(field, {})), "输入已改变：" + field)
    data, packages = root / "UmiOCR-data", runtime / "site-packages"
    source_mode = manifest.get("inputMode", "source") == "source"
    report = {"status": "RUNNING", "root": str(root), "runtime": str(runtime),
              "inputMode": "source-with-declared-runtime" if source_mode else "reinstalled-archive",
              "manifest": str(manifest_path), "manifestSha256": sha(manifest_path), "driverSha256": sha(__file__),
              "cases": [], "operations": [], "screenshots": [], "qtProblems": [], "errors": [],
              "scenarioCompleted": False, "normalExit": False, "models": "NOT_LOADED",
              "desktopCapture": "NOT_RUN", "realClipboard": "NOT_READ_OR_CHANGED", "childProcesses": []}
    processes, handles = [], []
    original_engine = original_installer = original_popen = None
    finder = None
    started = time.monotonic()
    try:
        for variable, name in (("TEMP", "os-temp"), ("TMP", "os-temp"), ("XDG_CACHE_HOME", "os-cache"),
                               ("APPDATA", "os-roaming"), ("LOCALAPPDATA", "os-local"), ("QT_SHADER_CACHE_PATH", "qt-cache")):
            target = root / name
            target.mkdir(exist_ok=True)
            os.environ[variable] = str(target)
        os.environ["QML_DISABLE_DISK_CACHE"] = "1"
        sys.path[:0] = [str(packages), str(runtime / "dependencies.zip")]
        handles.append(os.add_dll_directory(str(packages / "PySide6")))
        namespace = runpy.run_path(str(data / "main.py"), run_name="workbench_actual_entry")
        namespace["initRuntimeEnvironment"]()
        import site
        if source_mode:
            site.addsitedir(str(data / "py_src/imports"))
        from PySide6 import QtCore, QtQml
        from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, QSettings, QTimer, Qt
        from PySide6.QtGui import QKeyEvent, QMouseEvent
        from PySide6.QtQml import QQmlEngine, QQmlExpression
        from PySide6.QtWidgets import QApplication
        import shiboken6
        QCoreApplication.setLibraryPaths([str(packages / "PySide6/plugins")])
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(packages / "PySide6/plugins/platforms")
        os.MessageBox = lambda message, *_args, **_kwargs: report["errors"].append("启动诊断：" + str(message))

        class NoInference(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in FORBIDDEN or fullname in {BASE.PP + ".worker", BASE.VL + ".worker"}:
                    report["errors"].append("已阻止推理导入：" + fullname)
                    raise RuntimeError("工作台验收禁止推理导入：" + fullname)
        finder = NoInference()
        sys.meta_path.insert(0, finder)
        from py_src.utils import cuda_device_probe
        bootstrap = cuda_device_probe._WORKER_BOOTSTRAP
        import subprocess
        original_popen = subprocess.Popen

        class ProbeOnly(original_popen):
            def __init__(self, *values, **options):
                argv = options.get("args", values[0] if values else None)
                require(HELPER.trusted_probe(options.get("executable"), argv, options.get("cwd"),
                        runtime / "runtime/python.exe", data, bootstrap), "只允许已有可信设备发现子进程")
                super().__init__(*values, **options)
                processes.append(self)
                report["childProcesses"].append({"pid": self.pid, "argv": argv})
        subprocess.Popen = ProbeOnly
        original_installer = QtCore.qInstallMessageHandler

        def install(handler):
            def observed(kind, context, text):
                if kind in (QtCore.QtMsgType.QtWarningMsg, QtCore.QtMsgType.QtCriticalMsg, QtCore.QtMsgType.QtFatalMsg):
                    report["qtProblems"].append({"kind": kind.name, "file": context.file, "line": context.line, "text": text})
                if handler:
                    handler(kind, context, text)
            return original_installer(observed)
        QtCore.qInstallMessageHandler = install
        settings = QSettings(str(data / ".settings"), QSettings.IniFormat)
        require(not settings.allKeys(), "仅接纳没有用户配置的新沙盒")
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        for key, value in {"Global/server.enable": False, "Global/server.port": port,
                           "Global/ocr.lifecycle.warmupMode": "lazy", "Global/ocr.lifecycle.cleanupPolicy": "never",
                           "Global/ui.theme": "Default Light", "Global/ui.scale": 1,
                           "Global/window.simpleNotificationType": "none",
                           "TabPageManager/openPageList": ["Navigation"], "TabPageManager/showPageIndex": 0,
                           "ScreenshotOCR/hotkey.screenshot": "", "ScreenshotOCR/hotkey.paste": "",
                           "ScreenshotOCR/hotkey.reScreenshot": ""}.items():
            settings.setValue(key, value)
        settings.sync()
        require(settings.status() == QSettings.NoError, "沙盒配置写入失败")
        del settings
        write_new(data / ".pre_settings", {"i18n": "zh_CN", "opengl": "", "server_port": port, "last_pid": -1, "last_ptime": -1})
        write_new(data / "plugins/.plugins_state", {})
        from py_src.utils import utils
        utils.copyText = lambda text: report.setdefault("sandboxCopies", []).append(text)
        original_engine = QtQml.QQmlApplicationEngine

        class Engine(original_engine):
            def load(self, *values):
                super().load(*values)
                require(self.rootObjects(), "实际 Main.qml 未生成窗口")
                window = self.rootObjects()[0]
                report["qmlEntry"] = str(values[0])
                self.begun = self.finished = False

                def js(code, obj=window):
                    expression = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
                    value = expression.evaluate()
                    require(not expression.hasError(), expression.error().toString())
                    if isinstance(value, tuple):
                        value = value[0]
                    return value.toVariant() if hasattr(value, "toVariant") else value

                def jjson(code, obj=window):
                    return json.loads(js("JSON.stringify(" + code + ")", obj))

                def wait(predicate, label):
                    yield from SCHEDULER.wait_transition(predicate, label=label, timeout=10)

                def walk(item):
                    yield item
                    for child in item.childItems():
                        yield from walk(child)

                def named(item, name):
                    # Repeater 委托的 QObject 父级不一定在页面下，按实际视觉树定位。
                    matches = [child for child in walk(item) if child.objectName() == name and child.isVisible()]
                    require(len(matches) == 1, "实际可见控件不唯一或缺失：" + name)
                    return matches[0]

                def visible(item):
                    if not shiboken6.isValid(item) or not item.isVisible() or item.width() <= 0 or item.height() <= 0:
                        return False
                    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
                    parent = item
                    while parent is not None:
                        if parent.clip() and not parent.boundingRect().contains(parent.mapFromScene(point)):
                            return False
                        parent = parent.parentItem()
                    return window.contentItem().boundingRect().contains(point)

                def click(item, label):
                    require(visible(item) and item.isEnabled(), "实际控件不在可交互视口：" + label)
                    local = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
                    global_point = item.mapToGlobal(QPointF(item.width() / 2, item.height() / 2))
                    for kind, button, buttons in ((QEvent.MouseMove, Qt.NoButton, Qt.NoButton),
                                                  (QEvent.MouseButtonPress, Qt.LeftButton, Qt.LeftButton),
                                                  (QEvent.MouseButtonRelease, Qt.LeftButton, Qt.NoButton)):
                        QCoreApplication.sendEvent(window, QMouseEvent(kind, local, global_point, button, buttons, Qt.NoModifier))
                    report["operations"].append({"label": label, "input": "actual-QQuickWindow-mouse-events"})

                def capture(name):
                    path = output.parent / (output.stem + "-" + name + ".png")
                    require(not path.exists(), "窗口图必须使用新路径")
                    image = window.grabWindow()
                    require(not image.isNull() and image.save(str(path)), "实际窗口图保存失败")
                    report["screenshots"].append({"path": str(path), "sha256": sha(path),
                                                  "width": image.width(), "height": image.height()})

                def settled():
                    return js("qmlapp.globalConfigs.applyPhase===0 && !qmlapp.globalConfigs.backendApplyPending && !qmlapp.globalConfigs.pluginRefreshPending")

                def scenario():
                    window.setWidth(1100)
                    window.setHeight(780)
                    yield from wait(settled, "首次配置应用")
                    report["version"] = js("UmiAbout.version.string")
                    report["window"] = {"title": window.title(), "logicalSize": [window.width(), window.height()],
                        "devicePixelRatio": window.devicePixelRatio(), "screen": window.screen().name(),
                        "logicalDpi": window.screen().logicalDotsPerInch()}
                    report["pluginStates"] = jjson("qmlapp.globalConfigs.pluginStates")
                    require(not js("qmlapp.globalConfigs.documentUiEnabled"), "默认窗口不应启用可选文档任务页")
                    require(not js("qmlapp.globalConfigs.getValue('server.enable')"), "不启用 HTTP")
                    home = js("qmlapp.tab.openTabPageByKey('Navigation')")
                    yield 300
                    tasks = [item for item in walk(home) if item.objectName().startswith("navigationTask_") and item.isVisible()]
                    require(len(tasks) == 4, "默认功能入口数量异常")
                    require(all(visible(item) for item in tasks), "默认窗口功能入口应直接可见")
                    capture("home-light-zh_CN")
                    require(not any(item.objectName() == "navigationModelSettings" for item in walk(home)),
                            "首页不再提供模型设置快捷入口")
                    click(named(home, "navigationPluginSettings"), "工作台→插件管理")
                    yield from wait(lambda: js("qmlapp.tab.pageList[qmlapp.tab.showPageIndex].info.key==='GlobalConfigsPage'"), "插件管理页面")
                    page = js("qmlapp.tab.pageList[qmlapp.tab.showPageIndex].obj")
                    yield 400
                    selected = js("confComp.currentGroupIndex", page)
                    groups = jjson("confComp.activeGroupItems().map(item=>item.key)", page)
                    report["pluginShortcut"] = {"selectedIndex": selected, "groups": groups,
                        "targetKey": js("confComp.navigationGroupKey", page),
                        "scroll": jjson("({position:confComp.ScrollBar.vertical.position,view:confComp.height,content:confComp.contentHeight})", page)}
                    require(0 <= selected < len(groups) and groups[selected] == "plugins", "插件管理入口未定位插件组")
                    # 用真实键盘在ScrollView步进；不能只测显式选中索引。
                    js("confComp.scrollToGroup(0);confComp.forceActiveFocus()", page)
                    yield 100
                    start_position = js("confComp.ScrollBar.vertical.position", page)
                    for _ in range(18):
                        for kind in (QEvent.KeyPress, QEvent.KeyRelease):
                            QCoreApplication.sendEvent(window, QKeyEvent(kind, Qt.Key_Down, Qt.NoModifier))
                        yield 15
                    require(js("confComp.ScrollBar.vertical.position", page) > start_position, "方向键应实际滚动设置")
                    require(js("confComp.navigationGroupKey==='' && confComp.currentGroupIndex>0", page), "键盘滚动后侧栏须恢复位置跟踪")
                    report['keyboardSettingsScroll'] = {'passed':True,'selectedIndex':js('confComp.currentGroupIndex',page)}
                    page.focusGroup('plugins.models')
                    yield 250
                    geometry = jjson("(function(){const item=qmlapp.globalConfigs.compList.find(v=>v.key==='plugins.models'&&v.title!==undefined);const y=item.mapToItem(confComp,0,0).y;return {y:y,view:confComp.height,line:size_.line}})()", page)
                    require(0 <= geometry['y'] + geometry['line'] < geometry['view'], "全局设置中的模型组标题必须真的在视口内")
                    report['modelSettingsGeometry'] = geometry
                    capture("models-light-zh_CN")
                    from py_src.utils.i18n_configs import I18n
                    for theme, language, scale in itertools.product(THEMES, LANGUAGES, (1, 1.5)):
                        js("qmlapp.globalConfigs.setValue('ui.theme'," + json.dumps(theme) + ",true)")
                        js("qmlapp.globalConfigs.setValue('ui.scale'," + str(scale) + ",true)")
                        js("qmlapp.globalConfigs.setValue('ui.i18n'," + json.dumps(language) + ",true)")
                        yield from wait(lambda: settled() and I18n.langCode == language, "主题／语言／字号应用")
                        require(js("size_.textScale===parseFloat(size_.languageScale)"), "热切语言必须同步文字缩放系数")
                        home = js("qmlapp.tab.openTabPageByKey('Navigation')")
                        yield 250
                        grid = named(home, "navigationTaskGrid")
                        tasks = [item for item in walk(home) if item.objectName().startswith("navigationTask_") and item.isVisible()]
                        require(len(tasks) == 4 and all(item.width() > 0 and item.height() >= item.implicitHeight() - 1 for item in tasks), "入口文本高度不足")
                        require(grid.width() <= home.width() and all(item.width() <= grid.width() + 1 for item in tasks), "入口横向越界")
                        require(all(item.property("description") for item in tasks), "用途说明缺失")
                        states = jjson("installedVersions", home)
                        require(len(states) == 1 + len(report["pluginStates"]), "版本区与实际安装清单不同")
                        if language != "zh_CN":
                            hint = QCoreApplication.translate("Navigation", "请在 OCR 功能页选择识别模型；全局设置用于配置模型与设备。")
                            require(hint and hint != "请在 OCR 功能页选择识别模型；全局设置用于配置模型与设备。", "新增实际 QM 译文缺失")
                        report["cases"].append({"theme": theme, "language": language, "scale": scale,
                                                 "columns": grid.property("columns"), "taskCount": len(tasks),
                                                 "versions": states, "sidebarCurrentGroup": js("qmlapp.globalConfigs.panelComponent.currentGroupIndex")})
                        if (theme, language, scale) in (("Neutral Dark", "zh_CN", 1), ("Default Light", "en_US", 1),
                                                        ("Default Light", "ja_JP", 1), ("Neutral Dark", "ta", 1.5)):
                            capture("home-" + theme.replace(" ", "-") + "-" + language + "-" + str(scale))
                    js("qmlapp.globalConfigs.setValue('ui.i18n','zh_CN',true)")
                    js("qmlapp.globalConfigs.setValue('ui.scale',1.5,true)")
                    window.setWidth(640)
                    window.setHeight(620)
                    yield from wait(settled, "窄窗口配置应用")
                    home = js("qmlapp.tab.openTabPageByKey('Navigation')")
                    yield 300
                    require(named(home, "navigationTaskGrid").property("columns") == 1, "窄窗口应纵向排列")
                    capture("home-narrow-150")
                    first = named(home, 'navigationTask_ScreenshotOCR')
                    first.forceActiveFocus(Qt.TabFocusReason)
                    seen = set()
                    expected_focus = {'navigationTask_'+key for key in ('ScreenshotOCR','BatchOCR','BatchDOC','QRCode')} | {'navigationPluginSettings'}
                    for _ in range(14):
                        focused = window.activeFocusItem()
                        if focused and focused.objectName() in expected_focus:
                            require(visible(focused), '窄窗口的键盘焦点必须滚动到可见区域')
                            seen.add(focused.objectName())
                        for kind in (QEvent.KeyPress,QEvent.KeyRelease):
                            QCoreApplication.sendEvent(window,QKeyEvent(kind,Qt.Key_Tab,Qt.NoModifier))
                        yield 20
                    require(seen >= expected_focus, '窄窗口Tab链没有覆盖全部任务及设置入口：'+repr(seen))
                    report['narrowKeyboardFocus'] = sorted(seen)
                    # 宽窗口恢复后，通过真实任务按钮进入批量图片页。
                    window.setWidth(1100)
                    window.setHeight(780)
                    js("qmlapp.globalConfigs.setValue('ui.scale',1,true)")
                    yield 250
                    entry = named(home, "navigationTask_BatchOCR")
                    require(visible(entry), "键盘入口必须处于实际视口")
                    entry.forceActiveFocus(Qt.TabFocusReason)
                    require(entry.property("visualFocus"), "键盘导航必须显示焦点边框")
                    for key, modifiers in ((Qt.Key_Tab, Qt.NoModifier), (Qt.Key_Backtab, Qt.ShiftModifier)):
                        for kind in (QEvent.KeyPress, QEvent.KeyRelease):
                            QCoreApplication.sendEvent(window, QKeyEvent(kind, key, modifiers))
                    require(window.activeFocusItem() == entry, "Tab／Shift+Tab 必须回到原功能入口")
                    for kind in (QEvent.KeyPress, QEvent.KeyRelease):
                        QCoreApplication.sendEvent(window, QKeyEvent(kind, Qt.Key_Space, Qt.NoModifier))
                    report["operations"].append({"label": "键盘打开批量图片 OCR", "input": "actual-QQuickWindow-key-events", "key": "Space"})
                    yield from wait(lambda: js("qmlapp.tab.pageList[qmlapp.tab.showPageIndex].info.key==='BatchOCR'"), "批量图片页面")
                    # 页面键先变化，旧页destroy和左右栏布局要经过后续事件循环／渲染。
                    yield 350
                    batch = js("qmlapp.tab.pageList[qmlapp.tab.showPageIndex].obj")
                    require(visible(named(batch,'batchOcrFilesTable')), '批量导入表必须完成布局并可见')
                    require(not shiboken6.isValid(home) or not home.isVisible(), '不能带着工作台旧页残影取图')
                    capture("batch-ocr-empty")
                    require(not any(name.split(".")[0] in FORBIDDEN for name in sys.modules), "不应载入推理依赖")
                    report["scenarioCompleted"] = True

                def finish(error=None):
                    if self.finished:
                        return
                    self.finished = True
                    if error is not None:
                        report["errors"].append("".join(traceback.format_exception(type(error), error, error.__traceback__)))
                        try:
                            capture("failure")
                        except Exception as capture_error:
                            report["errors"].append(str(capture_error))
                    QApplication.instance().quit()

                def begin():
                    if self.begun:
                        return
                    self.begun = True
                    SCHEDULER.start_steps(scenario(), QTimer.singleShot, finish, finish)

                window.frameSwapped.connect(lambda: QTimer.singleShot(0, begin) if not self.begun else None)
                window.show()
                QTimer.singleShot(12000, lambda: finish(AssertionError("没有真实首帧")) if not self.begun else None)
                QTimer.singleShot(180000, lambda: finish(AssertionError("窗口场景超过有限期限")) if not self.finished else None)

        QtQml.QQmlApplicationEngine = Engine
        from py_src.run import main as run_application
        report["applicationModule"] = str(sys.modules["py_src.run"].__file__)
        require(str(root) in report["applicationModule"], "不能回退工作区或其他包的业务代码")
        sys.argv = [str(root / "Umi-OCR.exe"), "--force"]
        try:
            run_application(str(root / "Umi-OCR.exe"), str(packages / "PySide6/qml"))
        except SystemExit as error:
            if error.code not in (0, None):
                raise
        report["normalExit"] = True
    except Exception as error:
        report["errors"].append("".join(traceback.format_exception(type(error), error, error.__traceback__)))
    finally:
        if original_engine is not None:
            QtQml.QQmlApplicationEngine = original_engine
        if original_installer is not None:
            QtCore.qInstallMessageHandler = original_installer
        if original_popen is not None:
            subprocess.Popen = original_popen
        if finder is not None and finder in sys.meta_path:
            sys.meta_path.remove(finder)
        report["unexitedChildPids"] = [process.pid for process in processes if process.poll() is None]
        report["elapsedSeconds"] = round(time.monotonic() - started, 3)
        report["status"] = "PASS" if (report["scenarioCompleted"] and report["normalExit"] and len(report["cases"]) == 28
                                          and not report["errors"] and not report["qtProblems"] and not report["unexitedChildPids"]) else "FAIL"
        report["limits"] = "真实Main.qml及窗口内事件；配置和示例均为本轮沙盒。未运行模型、截图捕获/HDR/混屏；源码借用声明依赖不等于包内验收。"
        write_new(output, report)
    print(json.dumps({"status": report["status"], "cases": len(report["cases"]), "screenshots": len(report["screenshots"]),
                      "errors": report["errors"], "qtProblems": report["qtProblems"], "output": str(output)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--work-root", type=Path, required=True)
    prep.add_argument("--audit-root", type=Path, required=True)
    prep.add_argument("--runtime-data", type=Path, required=True)
    prep.add_argument("--name", default="source-ui-r1")
    execute = sub.add_parser("run")
    execute.add_argument("--manifest", type=Path, required=True)
    execute.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
