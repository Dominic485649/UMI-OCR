"""Windows 原生 Qt 界面定向验收驱动；默认运行候选测试副本，不运行推理。

示例：runtime/python.exe -B -I 此文件 --root <build/staging 下全新测试副本>
      --output <新审计JSON> --profile base|cuda-vl
准备阶段只执行 --self-test --output <新审计JSON>，不会导入 Qt 或启动应用。
每轮使用所验包自己的 Python/main/app.zip/ui.rcc，复用 test_hot_ui.py 的
QTimer 生成器调度；截图仅来自本应用 QQuickWindow.grabWindow()。
"""

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import importlib.abc
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile

REPO = Path(__file__).resolve().parents[1]
SETTINGS_NAMES = (".settings", ".pre_settings", "plugins/.plugins_state", "themes.json")
LANGUAGES = (
    ("zh_CN", ("zh_CN",), "简体中文"),
    ("zh_TW", ("zh_TW", "zh_HK"), "繁體中文"),
    ("en_US", ("en_US", "en"), "English"),
    ("ja_JP", ("ja_JP",), "日本語"),
    ("pt", ("pt", "pt_BR", "pt_PT"), "Português"),
    ("ru_RU", ("ru_RU", "ru"), "Русский"),
    ("ta", ("ta", "ta_TA"), "தமிழ்"),
)
PAGE_KEYS = ("Navigation", "GlobalConfigsPage", "ScreenshotOCR", "BatchOCR", "BatchDOC")


class ProbeUnavailable(RuntimeError):
    """运行时观测接口不可访问，必须记 NOT_RUN 而不是静态替代通过。"""


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def reparse(path):
    info = Path(path).lstat()
    return bool(getattr(info, "st_file_attributes", 0) & 0x400) or Path(path).is_symlink()


def checked_output(path):
    output = Path(path).absolute()
    audit = (REPO / "build/audit").resolve()
    if not output.resolve().is_relative_to(audit):
        raise ValueError("output必须放在本项目build/audit下的新证据路径。")
    for parent in output.parents:
        if parent.exists() and reparse(parent):
            raise ValueError(f"证据目录含链接或junction：{parent}")
        if parent.resolve() == audit:
            break
    if output.exists():
        raise FileExistsError(output)
    return output.resolve()


def checked_root(root, repo=REPO):
    """只允许本项目 build/staging、build/tmp 内的测试副本，拒绝正式安装和链接。"""
    original = Path(root).absolute()
    candidate = original.resolve()
    allowed = (repo / "build/staging", repo / "build/tmp")
    if not any(candidate.is_relative_to(parent.resolve()) for parent in allowed):
        raise ValueError("root 必须是本项目 build/staging 或 build/tmp 下的候选测试副本。")
    for path in (original, *original.parents):
        if path.exists() and reparse(path):
            raise ValueError(f"拒绝链接或 junction：{path}")
        if path == repo:
            break
    if not (candidate / "Umi-OCR.exe").is_file():
        raise ValueError("测试副本缺少实际主程序Umi-OCR.exe。")
    data = candidate / "UmiOCR-data"
    for relative in ("main.py", "runtime/python.exe", "about.json"):
        path = data / relative
        if not path.is_file() or not path.resolve().is_relative_to(data):
            raise ValueError(f"测试副本缺少或越界：{path}")
    for path in (data, data / "runtime", data / "site-packages", data / "plugins", data / "i18n"):
        if path.exists() and reparse(path):
            raise ValueError(f"拒绝依赖目录链接：{path}")
    return candidate


class SettingsSnapshot:
    def __init__(self, data):
        self.data = Path(data)
        self.saved = {}
        for name in SETTINGS_NAMES:
            path = self.data / name
            if not path.resolve().is_relative_to(self.data.resolve()):
                raise ValueError(f"测试配置路径越界：{path}")
            if path.exists() and (reparse(path) or not path.is_file()):
                raise ValueError(f"测试配置不是普通文件：{path}")
            self.saved[name] = path.read_bytes() if path.is_file() else None

    def fingerprints(self):
        return {name: hashlib.sha256(value).hexdigest() if value is not None else None
                for name, value in self.saved.items()}

    def restore(self):
        for name, value in self.saved.items():
            path = self.data / name
            if not path.resolve().is_relative_to(self.data.resolve()):
                raise ValueError(f"恢复时配置路径越界，停止：{path}")
            if path.exists() and (reparse(path) or not path.is_file()):
                raise ValueError(f"恢复时遇到新链接或异常文件，停止：{path}")
            if value is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(value)
        return all((self.data / name).read_bytes() == value if value is not None
                   else not (self.data / name).exists() for name, value in self.saved.items())


def choose_languages(options):
    available = {str(code): str(name) for code, name in options}
    chosen = []
    for canonical, aliases, name in LANGUAGES:
        code = next((code for code in aliases if code in available), None)
        chosen.append({"language": canonical, "code": code, "autonym": name})
    names = {code: name for _canonical, aliases, name in LANGUAGES for code in aliases}
    bad = {code: value for code, value in available.items() if code not in names or names[code] != value}
    return chosen, bad


def sidebar_buttons(root):
    """Repeater委托的QObject父级并非视觉父级，必须沿childItems读取实际按钮。"""
    pending, buttons = list(root.childItems()), []
    while pending:
        child = pending.pop(0)
        meta = child.metaObject()
        if meta.indexOfProperty("text_") >= 0 and meta.indexOfProperty("bgPressColor_") >= 0:
            buttons.append({"text": str(child.property("text_")), "visible": bool(child.property("visible")),
                            "width": child.property("width"), "height": child.property("height")})
        pending.extend(child.childItems())
    return buttons


def sidebar_stable(samples):
    """只按连续实际观测判收敛，不能以等待结束或单个相等样本代替。"""
    return len(samples) >= 3 and all(sample.get("equal") and sample.get("translated") and sample.get("settled")
                                    and sample.get("buttons_match") for sample in samples[-3:])


def qml_error_status(source, line):
    """内部QML源码抛错必须FAIL；只有无法访问测试观测表达式才记NOT_RUN。"""
    if int(line) > 1 and str(source).lower().split("?")[0].endswith(".qml"):
        return "FAIL"
    return "NOT_RUN"


def acceptance(report):
    failed = [key for key, value in report.get("checks", {}).items() if value["status"] == "FAIL"]
    missing = [key for key, value in report.get("checks", {}).items()
               if value["status"] == "NOT_RUN" and value.get("required", True)]
    finished = report.get("scenario_completed") is True and report.get("normal_exit") is True
    complete = finished and not failed and not missing and report.get("settings_restored") is True
    return {"complete": complete, "failed": failed, "required_not_run": missing,
            "status": "PASS" if complete else ("FAIL" if failed or report.get("errors") else "INCOMPLETE")}


def load_scheduler():
    path = Path(__file__).with_name("test_hot_ui.py")
    spec = importlib.util.spec_from_file_location("native_ui_existing_scheduler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def package_inputs(root):
    data = Path(root) / "UmiOCR-data"
    files = [Path(root) / "Umi-OCR.exe"]
    files += [data / name for name in ("main.py", "app.zip", "ui.rcc", "about.json", "runtime/python.exe")]
    files += sorted((data / "runtime").glob("python*.dll"))
    files += sorted((data / "i18n").glob("*.qm"))
    files += sorted((data / "plugins").glob("*/umi-plugin.json"))
    for path in files:
        if path.exists() and not path.resolve().is_relative_to(Path(root).resolve()):
            raise ValueError(f"候选载荷通过链接越界：{path}")
    files += [Path(__file__), Path(__file__).with_name("test_hot_ui.py")]
    return {str(path): sha256(path) for path in files if path.is_file()}


def candidate_processes(root):
    """只查询进程路径；不终止进程，不读取或截取其它应用窗口。"""
    if sys.platform != "win32":
        raise RuntimeError("原生驱动只能在 Windows 运行。")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32FirstW.restype = kernel.Process32NextW.restype = wintypes.BOOL
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    result, denied = [], 0
    entry = Entry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        more = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while more:
            pid = int(entry.th32ProcessID)
            if pid not in (0, os.getpid(), os.getppid()):
                process = kernel.OpenProcess(0x1000, False, pid)
                if process:
                    try:
                        size, buffer = wintypes.DWORD(32768), ctypes.create_unicode_buffer(32768)
                        if kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                            path = Path(buffer.value).resolve()
                            if path.is_relative_to(root):
                                result.append({"pid": pid, "executable": str(path)})
                        else:
                            denied += 1
                    finally:
                        kernel.CloseHandle(process)
                else:
                    denied += 1
            more = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    return {"candidate_processes": result, "unqueryable_system_process_count": denied}


def dwm_dark(hwnd):
    getter = ctypes.WinDLL("dwmapi").DwmGetWindowAttribute
    getter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    getter.restype = ctypes.c_long
    failures = []
    for attribute in (20, 19):
        value = wintypes.BOOL()
        code = getter(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
        if code >= 0:
            return {"available": True, "dark": bool(value.value), "attribute": attribute, "hwnd": int(hwnd)}
        failures.append(f"{attribute}:0x{code & 0xffffffff:08X}")
    return {"available": False, "hwnd": int(hwnd), "reason": "; ".join(failures)}


def win32_window_info(hwnd):
    user = ctypes.WinDLL("user32", use_last_error=True)
    getter = getattr(user, "GetWindowLongPtrW", user.GetWindowLongW)
    getter.argtypes = [wintypes.HWND, ctypes.c_int]
    getter.restype = ctypes.c_ssize_t
    style = int(getter(hwnd, -20))
    value = {"extended_style": style, "topmost": bool(style & 8)}
    if hasattr(user, "GetDpiForWindow"):
        user.GetDpiForWindow.argtypes = [wintypes.HWND]
        user.GetDpiForWindow.restype = wintypes.UINT
        value["dpi_for_window"] = int(user.GetDpiForWindow(hwnd))
    return value


def native_worker(args):
    root = checked_root(args.root)
    data, output = root / "UmiOCR-data", args.output.resolve()
    if Path(sys.executable).resolve() != (data / "runtime/python.exe").resolve():
        raise RuntimeError("worker 必须由被验候选包自身的 runtime/python.exe 启动。")
    if output.exists():
        raise FileExistsError(output)
    occupied = candidate_processes(root)
    if occupied["candidate_processes"]:
        raise RuntimeError(f"候选副本正被其它进程使用，拒绝修改配置：{occupied}")
    snapshot = SettingsSnapshot(data)
    report = {"mode": "native-windows-qt", "profile": args.profile, "boot": args.boot,
              "root": str(root), "python": sys.version, "executable": sys.executable,
              "input_sha256": package_inputs(root), "settings_before": snapshot.fingerprints(),
              "process_preflight": occupied, "checks": {}, "errors": [], "screenshots": [],
              "scenario_completed": False, "normal_exit": False, "settings_restored": False,
              "os": str(sys.getwindowsversion()), "gpu_inference_requested": False}
    report["diagnostic_only"] = bool(args.diagnose_language)
    for key in ("first_frame", "package_provenance", "no_gpu_runtime", "theme.initial", "theme.follow_system", "theme.follow_system.dwm",
                "theme.light.dwm", "theme.dark.dwm", "theme.topmost.dwm", "home.versions",
                "languages.autonyms", "models.shared", "services.visibility", "partial.results"):
        report["checks"][key] = {"status": "NOT_RUN", "reason": "场景尚未执行", "required": True}
    for canonical, _aliases, _name in LANGUAGES:
        report["checks"]["language." + canonical] = {"status": "NOT_RUN", "reason": "场景尚未执行", "required": args.boot == "fresh"}
    report["checks"]["system_theme_other_mode"] = {"status": "NOT_RUN", "required": False,
        "reason": "本驱动不修改操作系统主题；仅验收当前系统模式下的跟随与显式深浅主题。"}
    started, engines, previous_engine = time.monotonic(), [], None
    app = None
    sys.dont_write_bytecode = True
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    def check(name, status="PASS", **details):
        report["checks"][name] = {"status": status, "required": True, **details}
    def require(condition, message):
        if not condition:
            raise AssertionError(message)
    # 测试安全门禁不伪造推理结果；若业务意外请求模型则阻止并明确判失败。
    report["safety_blocks"] = []
    forbidden_modules = {"paddle", "paddleocr", "paddlex", "onnxruntime", "torch", "transformers"}
    class NoInferenceImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in forbidden_modules:
                report["safety_blocks"].append({"kind": "inference_import", "module": fullname})
                raise RuntimeError("UI驱动禁止加载推理模块：" + fullname)
            return None
    safety_finder = NoInferenceImports()
    sys.meta_path.insert(0, safety_finder)
    def no_child_process(event, values):
        if event == "subprocess.Popen":
            report["safety_blocks"].append({"kind": "child_process", "executable": str(values[0])[:300]})
            raise RuntimeError("UI驱动禁止启动模型或其它子进程；请检查业务是否意外预热。")
    sys.addaudithook(no_child_process)
    try:
        namespace = runpy.run_path(str(data / "main.py"), run_name="native_candidate_bootstrap")
        namespace["initRuntimeEnvironment"]()
        os.MessageBox = lambda message, *a, **k: report["errors"].append("包启动诊断：" + str(message))
        from PySide6 import QtQml
        from PySide6.QtCore import QCoreApplication, QEvent, QFile, QIODevice, QPointF, QSettings, QTimer, Qt
        from PySide6.QtGui import QGuiApplication, QMouseEvent
        from PySide6.QtQml import QQmlEngine, QQmlExpression
        from PySide6.QtWidgets import QApplication
        # 仅修改候选测试副本；原始字节在本进程正常结束后逐项恢复。
        settings = QSettings(str(data / ".settings"), QSettings.Format.IniFormat)
        settings.setFallbacksEnabled(False)
        settings.clear()
        prepared = {"Global/server.enable": False, "Global/ocr.lifecycle.warmupMode": "lazy",
                    "Global/ocr.lifecycle.cleanupPolicy": "never", "Global/window.startupInvisible": False,
                    "Global/window.messageMemory": ["globalConfigsKey"], "Global/window.simpleNotificationType": "none",
                    "TabPageManager/openPageList": ["Navigation"], "TabPageManager/showPageIndex": 0,
                    "ScreenshotOCR/hotkey.screenshot": "", "ScreenshotOCR/hotkey.paste": "",
                    "ScreenshotOCR/hotkey.reScreenshot": ""}
        if args.boot == "saved-light":
            prepared["Global/ui.theme"] = "Default Light"
        for key, value in prepared.items():
            settings.setValue(key, value)
        settings.sync()
        require(settings.status() == QSettings.Status.NoError, "候选副本配置准备失败")
        del settings
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        (data / ".pre_settings").write_text(json.dumps({"i18n": "zh_CN", "opengl": "", "server_port": port,
            "last_pid": -1, "last_ptime": -1}), encoding="utf-8")
        if (data / "plugins").is_dir():
            (data / "plugins/.plugins_state").write_text("{}", encoding="utf-8")
        scheduler = load_scheduler()
        previous_engine = QtQml.QQmlApplicationEngine
        def evaluate(engine, obj, code):
            expression = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
            value = expression.evaluate()
            if expression.hasError():
                error = expression.error()
                if qml_error_status(error.url().toString(), error.line()) == "FAIL":
                    raise AssertionError("真实QML运行时异常：" + error.toString())
                raise ProbeUnavailable(error.toString())
            if isinstance(value, tuple):
                value = value[0]
            return value.toVariant() if hasattr(value, "toVariant") else value
        class Engine(previous_engine):
            def load(self, *values):
                super().load(*values)
                engines.append(self)
                require(bool(self.rootObjects()), "包没有创建真实 QML 主窗口")
                window = self.rootObjects()[0]
                self.window, self.finished, self.begun, self.active_check = window, False, False, "first_frame"
                def js(code, obj=window):
                    return evaluate(self, obj, code)
                def jjson(code, obj=window):
                    encoded = js("JSON.stringify(" + code + ")", obj)
                    if not isinstance(encoded, str):
                        raise ProbeUnavailable("运行时对象无法序列化，不能用静态值替代：" + code[:180])
                    return json.loads(encoded)
                def finish(error=None):
                    if self.finished:
                        return
                    self.finished = True
                    if error is not None:
                        message = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                        if isinstance(error, ProbeUnavailable):
                            report.setdefault("diagnostics", []).append(message)
                            check(self.active_check, "NOT_RUN", reason=str(error))
                        else:
                            report["errors"].append(message)
                            check(self.active_check, "FAIL", reason=str(error))
                    QApplication.instance().quit()
                def settled():
                    return bool(js("qmlapp.globalConfigs.applyPhase===0 && !qmlapp.globalConfigs.backendApplyPending && !qmlapp.globalConfigs.pluginRefreshPending && !qmlapp.globalConfigs.ocrManager.applying && !qmlapp.globalConfigs.documentManager.applying && !qmlapp.msnConnector.isBusy()"))
                def wait(predicate, label, timeout=20):
                    yield from scheduler.wait_transition(predicate, timeout=timeout, label=label)
                def activate(key):
                    page = js("qmlapp.tab.openTabPageByKey(" + json.dumps(key) + ")")
                    require(page is not None, f"页面无法实际创建：{key}")
                    return page
                def set_value(key, value):
                    js("qmlapp.globalConfigs.setValue(" + json.dumps(key) + "," + json.dumps(value, ensure_ascii=False) + ",true)")
                def capture(label):
                    if len(report["screenshots"]) >= args.max_screenshots:
                        report.setdefault("capture_skips", []).append({"label": label, "status": "NOT_RUN", "reason": "已达到有限截图预算"})
                        return
                    image = window.grabWindow()
                    require(not image.isNull(), "应用窗口截图为空")
                    path = output.with_name(output.stem + "-" + label + ".png")
                    require(not path.exists(), f"截图证据已存在：{path}")
                    require(image.save(str(path)), "无法保存本应用窗口截图")
                    report["screenshots"].append({"path": str(path), "sha256": sha256(path),
                        "width": image.width(), "height": image.height(), "capture": "QQuickWindow.grabWindow-only"})
                def no_gpu():
                    require(not report["safety_blocks"], f"UI业务触发了被门禁阻止的推理/子进程：{report['safety_blocks']}")
                    forbidden = sorted(name for name in sys.modules if name.split(".")[0] in
                                       {"paddle", "paddleocr", "paddlex", "onnxruntime", "torch", "transformers"})
                    require(not forbidden, f"UI 验收不应加载推理模块：{forbidden[:8]}")
                    states = {}
                    from py_src.plugins_controller.services import PluginServices
                    for key, entry in PluginServices._entries.items():
                        instance = entry.get("instance")
                        state = instance.get_status() if instance and callable(getattr(instance, "get_status", None)) else {}
                        states["/".join(key)] = state
                        require(not state.get("pid") and state.get("state") not in ("ready", "busy", "starting", "sleeping"),
                                f"UI 验收意外启动模型服务：{key} {state}")
                    status = jjson("qmlapp.msnConnector.callPy('ocr','getStatus',[])")
                    require((status.get("apiState") or {}).get("state") not in ("loaded", "warming", "busy"), status)
                    check("no_gpu_runtime", forbidden_modules=forbidden, service_states=states, mission_status=status)
                def provenance():
                    modules = {}
                    for name, module in list(sys.modules.items()):
                        if name == "py_src" or name.startswith("py_src.") or name in ("umi_about", "umi_log", "plugin_i18n") or name.startswith(("PySide6.", "shiboken6")):
                            origin = getattr(module, "__file__", None)
                            if origin:
                                require(Path(origin).resolve().is_relative_to(data), f"模块来自包外：{name}: {origin}")
                                modules[name] = str(origin)
                    require("py_src.run" in modules, "未观察到所验包的 py_src.run")
                    qml_origins, qml_hashes = set(), {}
                    for obj in [window, *window.findChildren(__import__("PySide6.QtCore", fromlist=["QObject"]).QObject)]:
                        context = QQmlEngine.contextForObject(obj)
                        if context is None:
                            continue
                        url = context.baseUrl()
                        text = url.toString()
                        if "/qt_res/qml/" not in text and "/plugins/" not in text:
                            continue
                        if url.isLocalFile():
                            path = Path(url.toLocalFile()).resolve()
                            require(path.is_relative_to(data), f"QML 来自候选包外：{text}")
                            if path.is_file():
                                qml_hashes[text] = sha256(path)
                        elif url.scheme() == "qrc":
                            require((data / "ui.rcc").is_file(), "资源 QML 无对应被验 ui.rcc")
                            source = QFile(":" + url.path())
                            require(source.open(QIODevice.OpenModeFlag.ReadOnly), f"不能读取已加载QML资源：{text}")
                            qml_hashes[text] = hashlib.sha256(bytes(source.readAll())).hexdigest()
                            source.close()
                        else:
                            raise AssertionError(f"无法证明 QML 载荷归属：{text}")
                        qml_origins.add(text)
                    require(any(text.endswith("/Main.qml") for text in qml_origins), "没有主窗口 QML 的运行时来源证据")
                    source_members = {}
                    archive = data / "app.zip"
                    if archive.is_file():
                        with zipfile.ZipFile(archive) as payload:
                            for member in ("py_src/run.py", "py_src/utils/theme_connector.py", "py_src/utils/i18n_configs.py"):
                                if member in payload.namelist():
                                    source_members[member] = hashlib.sha256(payload.read(member)).hexdigest()
                    check("package_provenance", modules=modules, qml_origins=sorted(qml_origins),
                          loaded_qml_sha256=qml_hashes, embedded_source_sha256=source_members)
                def home_versions(home):
                    states = jjson("qmlapp.globalConfigs.pluginStates")
                    actual = jjson("installedVersions", home)
                    require(len(actual) == 1 + len(states), f"版本区虚构或漏显示插件：{actual} {states}")
                    require(actual[0] == "Umi-OCR  " + str(js("UmiAbout.version.string")), actual)
                    manifests = {}
                    for state, line in zip(states, actual[1:]):
                        require(str(state.get("version") or "-") in line and str(state.get("name") or state["id"]) in line, (state, line))
                        manifest = data / "plugins" / state["id"] / "umi-plugin.json"
                        if manifest.is_file():
                            value = json.loads(manifest.read_text(encoding="utf-8"))
                            require(str(value["version"]) == str(state.get("version")), (value, state))
                            manifests[state["id"]] = {"version": value["version"], "sha256": sha256(manifest)}
                        if state["state"] == "disabled":
                            label = js("qmlapp.globalConfigs.pluginStateText('disabled')")
                            require(label in line, (label, line))
                    before = list(actual)
                    js("introText='NATIVE_UI_HOVER_INTRO'", home)
                    require(jjson("installedVersions", home) == before, "简介变化使独立版本区消失")
                    check("home.versions", plugin_states=states, rendered_lines=actual, manifests=manifests,
                          absence_checked="行数与真实安装清单逐项对应；不存在的插件没有展示行")
                def native_theme(name, expected):
                    observation = dwm_dark(int(window.winId()))
                    if not observation["available"]:
                        check(name, "NOT_RUN", reason="DWM 属性不可读", observation=observation)
                        return
                    yield from wait(lambda: dwm_dark(int(window.winId())).get("dark") == expected, name, timeout=5)
                    observation = dwm_dark(int(window.winId()))
                    require(observation.get("dark") == expected, (name, observation, expected))
                    check(name, observation=observation, software_dark=bool(js("theme.manager.appliedDark")),
                          background=js("theme.bgColor.toString()"))
                def visible_text_items(root, needles):
                    """只读实际视觉树；过滤隐藏、动画透明及被祖先裁切的文本中心。"""
                    pending, matches, targets = [root], {key: [] for key in needles}, {}
                    while pending:
                        item = pending.pop(0)
                        pending.extend(item.childItems())
                        if item.metaObject().indexOfProperty("text") < 0:
                            continue
                        text = str(item.property("text") or "")
                        keys = [key for key, needle in needles.items() if needle in text]
                        width, height = float(item.property("width") or 0), float(item.property("height") or 0)
                        if not keys or not item.property("visible") or width <= 0 or height <= 0:
                            continue
                        center = item.mapToScene(QPointF(width / 2, height / 2))
                        if not (0 <= center.x() < window.width() and 0 <= center.y() < window.height()):
                            continue
                        ancestor, exposed = item, True
                        while ancestor is not None:
                            if not ancestor.property("visible") or float(ancestor.property("opacity") or 0) < 0.95:
                                exposed = False
                                break
                            if ancestor.property("clip") and not ancestor.boundingRect().contains(ancestor.mapFromScene(center)):
                                exposed = False
                                break
                            ancestor = ancestor.parentItem()
                        if not exposed:
                            continue
                        context = QQmlEngine.contextForObject(item)
                        info = {"text": text, "width": width, "height": height,
                                "scene_center": [center.x(), center.y()],
                                "qml": context.baseUrl().toString() if context is not None else None}
                        for key in keys:
                            matches[key].append(info)
                            targets.setdefault(key, item)
                    return matches, targets
                def sidebar_snapshot(global_page):
                    left = jjson("groupList", global_page)
                    current = jjson("qmlapp.globalConfigs.panelComponent.getGroupList() || null")
                    controls_root = js("leftTop", global_page)
                    if controls_root is None:
                        raise ProbeUnavailable("不能访问实际全局设置左栏的控件根")
                    buttons = sidebar_buttons(controls_root)
                    expected = QCoreApplication.translate("GlobalConfigs", "界面和外观")
                    origin_title = js("qmlapp.globalConfigs.originDict['ui'].title")
                    left_titles = [item["title"] for item in (left or [])]
                    current_titles = [item["title"] for item in (current or [])]
                    advanced = bool(js("qmlapp.globalConfigs.panelComponent.advanced"))
                    expected_visible = [not item["advanced"] or advanced for item in (left or [])]
                    return {"left": left, "panel": current, "left_buttons": buttons,
                        "origin_ui_title": origin_title, "expected_ui_title": expected,
                        "equal": bool(left) and left == current,
                        "translated": expected in left_titles and expected in current_titles and origin_title == expected,
                        "buttons_match": bool(buttons) and [item["text"] for item in buttons] == left_titles
                            and (not global_page.property("visible") or
                                 [item["visible"] for item in buttons] == expected_visible)
                            and all(item["width"] > 0 and item["height"] > 0 for item in buttons if item["visible"])}
                def wait_sidebar(global_page, label):
                    samples = []
                    report.setdefault("language_sidebar_samples", {})[label] = samples
                    start = time.monotonic()
                    while True:
                        sample = sidebar_snapshot(global_page)
                        sample.update({"ms": round((time.monotonic() - start) * 1000, 2), "settled": settled()})
                        samples.append(sample)
                        if sidebar_stable(samples):
                            return sample
                        require(time.monotonic() - start < 2.5, "已开全局设置左栏/实际按钮在2500ms内未收敛：" + json.dumps(sample, ensure_ascii=False))
                        yield 50
                def diagnose_sidebar(global_page, target):
                    from py_src.utils.i18n_configs import I18n
                    diagnostic = {"target": target, "wait_budget_ms_per_phase": 2500, "signals": [], "phases": []}
                    report["language_diagnostics"] = diagnostic
                    global_object = js("qmlapp.globalConfigs")
                    callbacks = []
                    for signal_name in ("panelRebuilt", "configurationReloaded"):
                        signal = getattr(global_object, signal_name)
                        def callback(kind=signal_name):
                            if len(diagnostic["signals"]) < 128:
                                diagnostic["signals"].append({"kind": kind, "seconds": round(time.monotonic() - started, 4),
                                    "revision": global_object.property("definitionRevision")})
                        signal.connect(callback)
                        callbacks.append((signal, callback))
                    def observe(operation_start):
                        state = jjson("({applyPhase:qmlapp.globalConfigs.applyPhase,backendApplyPending:qmlapp.globalConfigs.backendApplyPending,pluginRefreshPending:qmlapp.globalConfigs.pluginRefreshPending,panelBuilt:qmlapp.globalConfigs.panelBuilt,definitionRevision:qmlapp.globalConfigs.definitionRevision,isChangedInit:qmlapp.globalConfigs.isChangedInit,bridgeBusy:qmlapp.msnConnector.isBusy()})")
                        return {**sidebar_snapshot(global_page),
                            "ms": round((time.monotonic() - operation_start) * 1000, 2),
                            "seconds": round(time.monotonic() - started, 4), "language": I18n.langCode,
                            "global_page_visible": bool(global_page.property("visible")), "state": state,
                            "component_groups": jjson("qmlapp.globalConfigs.compList.filter(function(c){return c.key && c.key.indexOf('.')<0 && c.title!==undefined}).map(function(c){return {key:c.key,title:c.title,advanced:!!c.advanced}})"),
                            "settled": settled() and I18n.langCode in ("zh_CN", target)}
                    def series(label, operation_start):
                        phase = {"label": label, "samples": []}
                        diagnostic["phases"].append(phase)
                        for index in range(26):
                            phase["samples"].append(observe(operation_start))
                            if index < 25:
                                yield 100
                        first, last = phase["samples"][0], phase["samples"][-1]
                        phase["summary"] = {"stable_last_three": sidebar_stable(phase["samples"]),
                            "first_equal_ms": next((sample["ms"] for sample in phase["samples"] if sample["equal"] and sample["translated"] and sample["settled"] and sample["buttons_match"]), None),
                            "first_left": first["left"], "first_panel": first["panel"],
                            "last_left": last["left"], "last_panel": last["panel"],
                            "last_buttons": last["left_buttons"], "last_state": last["state"],
                            "page_visible": last["global_page_visible"], "language": last["language"],
                            "last_sample_ms": last["ms"]}
                    try:
                        operation_start = time.monotonic()
                        set_value("ui.i18n", target)
                        yield from wait(lambda: settled() and I18n.langCode == target, "Diagnostic hidden language apply")
                        yield 50
                        yield from series("programmatic-hidden-target", operation_start)
                        operation_start = time.monotonic()
                        activate("GlobalConfigsPage")
                        yield from series("normal-tab-show-target", operation_start)
                        for code, label in (("zh_CN", "visible-control-zh_CN"), (target, "visible-control-target")):
                            operation_start = time.monotonic()
                            js("qmlapp.globalConfigs.compDict['ui.i18n'].value(" + json.dumps(code) + ")")
                            yield from wait(lambda: settled() and I18n.langCode == code, "Diagnostic actual visible language control")
                            yield from series(label, operation_start)
                        capture("language-visible-diagnostic")
                        no_gpu()
                        provenance()
                        diagnostic["summary"] = {phase["label"]: phase["summary"] for phase in diagnostic["phases"]}
                        visible_bad = [phase["label"] for phase in diagnostic["phases"]
                                       if phase["label"].startswith("visible-control-") and not phase["summary"]["stable_last_three"]]
                        diagnostic["visible_nonconverged_phases"] = visible_bad
                        report["diagnostic_completed"] = True
                        if visible_bad:
                            check("language." + target, "FAIL", reason="实际可见全局页经语言控件切换后，有限等待内左栏仍不与panel收敛", phases=visible_bad)
                        else:
                            check("language." + target, "NOT_RUN", reason="本轮只做有限时间序列诊断，不代替完整七语验收", required=False)
                    finally:
                        for signal, callback in callbacks:
                            signal.disconnect(callback)

                def scenario():
                    self.active_check = "first_frame"
                    check("first_frame", seconds=time.monotonic() - started, hwnd=int(window.winId()))
                    yield from wait(settled, "Initial package apply")
                    no_gpu()
                    screen = window.screen()
                    report["window"] = {"hwnd": int(window.winId()), "title": window.title(),
                        "geometry": [window.x(), window.y(), window.width(), window.height()],
                        "device_pixel_ratio": window.devicePixelRatio(), "screen": screen.name(),
                        "logical_dpi": screen.logicalDotsPerInch(), "physical_dpi": screen.physicalDotsPerInch(),
                        "system_color_scheme": str(QGuiApplication.styleHints().colorScheme()),
                        "win32": win32_window_info(int(window.winId()))}
                    report["cold_config_state"] = jjson("({lazyPanel:qmlapp.globalConfigs.lazyPanel,panelBuilt:qmlapp.globalConfigs.panelBuilt,mapType:typeof qmlapp.globalConfigs.compDict,originType:typeof qmlapp.globalConfigs.originDict})")
                    capture("initial")
                    self.active_check = "theme.initial"
                    initial = js("qmlapp.globalConfigs.getValue('ui.theme')")
                    default = js("qmlapp.globalConfigs.originDict['ui.theme'].default")
                    follow = js("theme.manager.followSystemKey")
                    require(default == follow, (default, follow))
                    require(initial == (follow if args.boot == "fresh" else "Default Light"), (args.boot, initial))
                    check("theme.initial", boot=args.boot, stored=initial, schema_default=default,
                          saved_explicit_preserved=args.boot == "saved-light")
                    self.active_check = "theme.follow_system"
                    set_value("ui.theme", follow)
                    yield 100
                    system_dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
                    expected_key = js("theme.manager.systemDarkTheme" if system_dark else "theme.manager.systemLightTheme")
                    require(js("theme.bgColor.toString().toLowerCase()===theme.all[" + json.dumps(expected_key) + "].bgColor.toLowerCase()"), expected_key)
                    if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Unknown:
                        check("theme.follow_system", "NOT_RUN", reason="Qt未提供当前系统深浅色，不能把回退浅色当系统主题已验证",
                              effective_key=expected_key)
                    else:
                        check("theme.follow_system", system_dark=system_dark, effective_key=expected_key,
                              effective_dark=bool(js("theme.manager.appliedDark")))
                    self.active_check = "theme.follow_system.dwm"
                    yield from native_theme("theme.follow_system.dwm", bool(js("theme.manager.appliedDark")))
                    self.active_check = "theme.light.dwm"
                    set_value("ui.theme", "Default Light")
                    yield 100
                    require(not js("theme.manager.appliedDark"), "显式浅色软件主题未生效")
                    yield from native_theme("theme.light.dwm", False)
                    self.active_check = "theme.dark.dwm"
                    set_value("ui.theme", "Neutral Dark")
                    yield 100
                    require(js("theme.manager.appliedDark"), "显式深色软件主题未生效")
                    yield from native_theme("theme.dark.dwm", True)
                    capture("dark")
                    self.active_check = "theme.topmost.dwm"
                    old_hwnd = int(window.winId())
                    set_value("window.isMainWindowTop", True)
                    yield 100
                    require(js("mainWindowRoot.isMainWindowTop"), "置顶标志未真正生效")
                    require(win32_window_info(int(window.winId()))["topmost"], "Win32 WS_EX_TOPMOST 未生效")
                    yield from native_theme("theme.topmost.dwm", True)
                    report["topmost_handles"] = {"before": old_hwnd, "after": int(window.winId()),
                        "recreated": old_hwnd != int(window.winId())}
                    set_value("window.isMainWindowTop", False)
                    yield 100
                    require(not win32_window_info(int(window.winId()))["topmost"], "解除置顶后Win32标志未恢复")
                    self.active_check = "theme.unpinned.dwm"
                    yield from native_theme("theme.unpinned.dwm", True)
                    set_value("ui.theme", "Default Light")
                    home, global_page = activate("Navigation"), activate("GlobalConfigsPage")
                    pages = {key: activate(key) for key in PAGE_KEYS[2:]}
                    yield 100
                    self.active_check = "home.versions"
                    home_versions(home)
                    self.active_check = "languages.autonyms"
                    options = jjson("qmlapp.globalConfigs.originDict['ui.i18n'].optionsList")
                    languages, bad = choose_languages(options)
                    require(not bad, f"语言选项不是自身名称或出现未支持语言：{bad}")
                    require(js("qmlapp.globalConfigs.originDict['ui.i18n'].title") == "语言/language", "固定语言标签错误")
                    check("languages.autonyms", options=options)
                    if args.diagnose_language:
                        self.active_check = "language." + args.diagnose_language
                        require(any(item["code"] == args.diagnose_language for item in languages), "实际包未提供诊断目标语言")
                        yield from diagnose_sidebar(global_page, args.diagnose_language)
                        return
                    if args.boot == "fresh":
                        from py_src.utils.i18n_configs import I18n
                        activate("GlobalConfigsPage")
                        for language in languages:
                            key = "language." + language["language"]
                            self.active_check = key
                            if language["code"] is None:
                                check(key, "NOT_RUN", reason="实际包未提供此语言选项")
                                continue
                            js("qmlapp.globalConfigs.compDict['ui.i18n'].value(" + json.dumps(language["code"]) + ")")
                            yield from wait(lambda: settled() and I18n.langCode == language["code"], key)
                            sidebar = yield from wait_sidebar(global_page, key)
                            require(js("qmlapp.globalConfigs.originDict['ui.i18n'].title") == "语言/language", key)
                            require(jjson("qmlapp.globalConfigs.originDict['ui.i18n'].optionsList") == options, "热切改变了语言自身名称")
                            navigation = jjson("(function(){var a=[];for(var i=0;i<pageModel.count;i++)a.push(pageModel.get(i));return a})()", home)
                            expected_nav = QCoreApplication.translate("PagesManager", "全局设置")
                            require(any(item["title"] == expected_nav for item in navigation), (key, expected_nav, navigation))
                            if language["language"] != "zh_CN":
                                require(expected_nav != "全局设置", "目标语言导航译文缺失，不能用原文回退当通过")
                            groups = sidebar["left"]
                            current_groups = sidebar["panel"]
                            require(groups == current_groups and bool(groups), "已开全局设置左栏未刷新")
                            expected_ui_group = QCoreApplication.translate("GlobalConfigs", "界面和外观")
                            require(any(item["title"] == expected_ui_group for item in groups), "全局设置左栏不是当前QTranslator译文")
                            require(js("qmlapp.globalConfigs.originDict['ui'].title") == expected_ui_group, "全局设置规范标题未热切")
                            if language["language"] != "zh_CN":
                                require(expected_ui_group != "界面和外观", "目标语言设置分组译文缺失")
                            screenshot = pages["ScreenshotOCR"]
                            expected_hotkeys = QCoreApplication.translate("ScreenshotOcrConfigs", "快捷键")
                            source_title = js("configsComp.originDict['hotkey'].title", screenshot)
                            controls = jjson("configsComp.compList.filter(function(c){return c.key==='hotkey'}).map(function(c){return c.title})", screenshot)
                            require(source_title == expected_hotkeys and controls == [expected_hotkeys], "已开截图设置快照未热切")
                            check(key, selected=I18n.langCode, navigation=navigation, group_list=groups,
                                  left_buttons=sidebar["left_buttons"], visible_control_switch=True,
                                  opened_screenshot_title=source_title, actual_language_label="语言/language")
                            no_gpu()
                        set_value("ui.i18n", "zh_CN")
                        yield from wait(settled, "Restore Chinese UI")
                    else:
                        for language in languages:
                            check("language." + language["language"], "NOT_RUN", required=False,
                                  reason="七语验收在fresh启动轮执行，本轮只补已有显式主题启动保留")
                    self.active_check = "models.shared"
                    options = jjson("qmlapp.globalConfigs.originDict['ocr.api'] ? qmlapp.globalConfigs.originDict['ocr.api'].optionsList : []")
                    if args.profile == "base":
                        require(not jjson("qmlapp.globalConfigs.pluginStates"), "base配置包含实际安装插件")
                        require(not options, "无插件基础包制造了模型假选项")
                        require(all(not js("configsComp.compList.some(function(c){return c.sourceKey==='ocr.api'})", page) for page in pages.values()), "无插件时仍显示模型选择")
                        check("models.shared", profile="base", absence_verified=True,
                              canonical_sync={"status": "NOT_RUN", "reason": "本配置未安装可选OCR后端"})
                    else:
                        states = jjson("qmlapp.globalConfigs.pluginStates")
                        require(any(item["id"] == "win32_PaddleOCRv6_CUDA" and item["state"] == "ready" for item in states), "cuda-vl缺少可用CUDA插件")
                        require(any(item["id"] == "win32_PaddleOCRVL_1_6" and item["state"] == "ready" for item in states), "cuda-vl缺少可用VL插件")
                        observations = []
                        for index, option in enumerate(options):
                            page = list(pages.values())[index % len(pages)]
                            js("configsComp.compList.find(function(c){return c.sourceKey==='ocr.api'}).value(" + json.dumps(option[0]) + ")", page)
                            yield from wait(settled, "Canonical model selection")
                            for other in pages.values():
                                require(js("configsComp.compList.find(function(c){return c.sourceKey==='ocr.api'}).value()", other) == option[0], "多个入口模型不同步")
                                require(not js("Object.prototype.hasOwnProperty.call(configsComp.valueDict,'ocr.api')", other), "页面保存了全局模型副本")
                            observations.append({"selected": option, "canonical": js("qmlapp.globalConfigs.getValue('ocr.api')")})
                        for source_key, value in (("ocr.lifecycle.warmupDelayMinutes", 59), ("ocr.lifecycle.idleCleanupMinutes", 37)):
                            js("configsComp.compList.find(function(c){return c.sourceKey==='" + source_key + "'}).value(" + str(value) + ")", pages["BatchOCR"])
                            yield 20
                            for other in pages.values():
                                require(js("configsComp.compList.find(function(c){return c.sourceKey==='" + source_key + "'}).value()", other) == value, "共享策略入口不同步")
                                require(not js("Object.prototype.hasOwnProperty.call(configsComp.valueDict,'" + source_key + "')", other), "生命周期误存到局部参数")
                        for source_key in ("ocr.lifecycle.warmupMode", "ocr.lifecycle.cleanupPolicy"):
                            canonical = js("qmlapp.globalConfigs.getValue('" + source_key + "')")
                            for other in pages.values():
                                require(js("configsComp.compList.find(function(c){return c.sourceKey==='" + source_key + "'}).value()", other) == canonical,
                                        "共享策略规范值与实际入口不一致")
                                require(not js("Object.prototype.hasOwnProperty.call(configsComp.valueDict,'" + source_key + "')", other), "共享枚举进入局部字典")
                        require(js("qmlapp.globalConfigs.getValue('ocr.lifecycle.warmupMode')") == "lazy", "验收不能启用后台模型预热")
                        check("models.shared", observations=observations, canonical_strategy_sync=True, cpu_required=False,
                              warmup_mode_mutation={"status": "NOT_RUN", "reason": "不启用延迟预热，避免测试加载GPU模型；验证现有规范引用和数值策略同步"})
                    self.active_check = "services.visibility"
                    def service_keys():
                        return jjson("qmlapp.globalConfigs.compList.filter(function(c){return c.key && c.key.indexOf('pluginServices.')===0}).map(function(c){return c.key})")
                    if args.profile == "base":
                        require(not service_keys(), "base显示了可选插件服务入口")
                        check("services.visibility", keys=[], absence_verified=True)
                    else:
                        vl = "win32_PaddleOCRVL_1_6"
                        prefix = "pluginServices." + vl + "."
                        require(any(key.startswith(prefix) for key in service_keys()), "启用VL未显示服务子项")
                        js("qmlapp.globalConfigs.setPluginEnabled(" + json.dumps(vl) + ",false)")
                        yield from wait(settled, "Disable VL service entry")
                        require(not any(key.startswith(prefix) for key in service_keys()), "禁用VL仍有可操作服务入口")
                        home_versions(home)
                        require(any(item["state"] == "disabled" and item["id"] == vl for item in jjson("qmlapp.globalConfigs.pluginStates")), "禁用状态未实际生效")
                        js("qmlapp.globalConfigs.setPluginEnabled(" + json.dumps(vl) + ",true)")
                        yield from wait(settled, "Enable VL service entry")
                        require(any(key.startswith(prefix) for key in service_keys()), "重新启用VL服务入口未恢复")
                        check("services.visibility", enabled_keys=service_keys(), disabled_hidden=True)
                    self.active_check = "partial.results"
                    screenshot = activate("ScreenshotOCR")
                    sample = {"code": 100, "timestamp": 1700000001, "time": 0.1, "title": "NATIVE_UI_SYNTHETIC",
                              "partial": True, "warnings": ["NATIVE_UI_PARTIAL_TEST_WARNING"],
                              "data": [{"text": "NATIVE_UI_TEXT_42", "box": [[0,0],[120,0],[120,24],[0,24]], "score": 0.9}]}
                    from PySide6.QtGui import QImage, QPainter
                    synthetic_path = output.with_name(output.stem + "-synthetic-input.png")
                    require(not synthetic_path.exists(), "合成输入证据路径已存在")
                    image = QImage(256, 96, QImage.Format.Format_RGB32)
                    image.fill(Qt.GlobalColor.white)
                    painter = QPainter(image)
                    painter.drawText(8, 28, "NATIVE_UI_TEXT_42")
                    painter.end()
                    require(image.save(str(synthetic_path)), "无法保存无隐私合成输入")
                    report["synthetic_input"] = {"path": str(synthetic_path), "sha256": sha256(synthetic_path), "capture": False}
                    js("onOcrGet(" + json.dumps(sample) + ",''," + json.dumps(str(synthetic_path)) + ")", screenshot)
                    yield from wait(lambda: js("imageText.showImage.status===Image.Ready", screenshot), "Synthetic image actual load")
                    yield 0
                    row = jjson("(function(){var r=resultsTableView.getResult('',1700000001);return {status:r.status__,title:r.title,text:r.resText,warning:r.warningText_}})()", screenshot)
                    require(row["status"] == "partial" and row["text"] == "NATIVE_UI_TEXT_42" and row["warning"] == "NATIVE_UI_PARTIAL_TEST_WARNING", row)
                    require("部分结果" in row["title"], row)
                    require(js("imageText.textBoxes.length", screenshot) == 1, "部分结果的有效叠加层被丢弃")
                    # onOcrGet尊重用户已选设置页；由驱动选择既有记录tab，不改产品自动切页规则。
                    js("tabPanel.currentIndex=1", screenshot)
                    record_root = js("resultsTableView", screenshot)
                    if record_root is None:
                        raise ProbeUnavailable("无法访问实际记录页视觉根")
                    record_needles = {"partial_title": "部分结果", "body": "NATIVE_UI_TEXT_42"}
                    record_samples = []
                    def record_ready():
                        matches, _targets = visible_text_items(record_root, record_needles)
                        if not all(matches.values()):
                            record_samples.clear()
                            return False
                        record_samples.append(matches)
                        del record_samples[:-3]
                        return len(record_samples) == 3 and all(
                            abs(sample[key][0]["scene_center"][axis] - record_samples[-1][key][0]["scene_center"][axis]) <= 0.5
                            for sample in record_samples for key in record_needles for axis in (0, 1))
                    yield from wait(record_ready, "Actual visible partial record title/body", timeout=2.5)
                    record_visual, record_targets = visible_text_items(record_root, record_needles)
                    require(all(record_visual.values()), "记录页可见文本在观测后消失")
                    # 只读取本测试写入的剪贴板；退出前恢复原始剪贴板格式。
                    clipboard = QApplication.clipboard()
                    original_mime = clipboard.mimeData()
                    saved_clipboard = {str(fmt): bytes(original_mime.data(fmt)) for fmt in original_mime.formats()} if original_mime else {}
                    try:
                        # 嵌入组件的根context属于调用页；公开ctrlBar别名锚定结果表内部作用域。
                        results_scope = js("resultsTableView.ctrlBar", screenshot)
                        if results_scope is None:
                            raise ProbeUnavailable("无法访问真实结果表的公开控制栏作用域")
                        js("tableMouseArea.selectAllCopy()", results_scope)
                        copied = clipboard.text()
                        require("NATIVE_UI_TEXT_42" in copied and "NATIVE_UI_PARTIAL_TEST_WARNING" not in copied, "记录复制混入警告")
                    finally:
                        from PySide6.QtCore import QMimeData
                        restored = QMimeData()
                        for fmt, value in saved_clipboard.items():
                            restored.setData(fmt, value)
                        clipboard.setMimeData(restored)
                    # 警告正文由原MouseArea悬停提示显示；只发送本窗口Qt事件，不移动OS鼠标。
                    title_item = record_targets["partial_title"]
                    title_point = QPointF(title_item.width() / 2, title_item.height() / 2)
                    local_point, global_point = title_item.mapToScene(title_point), title_item.mapToGlobal(title_point)
                    warning_visual = {}
                    def warning_ready():
                        matches, _targets = visible_text_items(window.contentItem(), {"warning": "NATIVE_UI_PARTIAL_TEST_WARNING"})
                        state = jjson("({inside:tableMouseArea.containsMouse,pressed:tableMouseArea.pressed,warning:tableMouseArea.hoverWarning})", results_scope)
                        warning_visual.clear()
                        warning_visual.update({"actual_visible_text": matches["warning"], "hover_state": state,
                            "event_scene_point": [local_point.x(), local_point.y()],
                            "input": "QMouseEvent(MouseMove) sent only to this QQuickWindow; no OS cursor movement"})
                        return bool(matches["warning"]) and state["inside"] and not state["pressed"] and state["warning"] == "NATIVE_UI_PARTIAL_TEST_WARNING"
                    QCoreApplication.sendEvent(window, QMouseEvent(QEvent.Type.MouseMove, local_point, global_point,
                        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
                    try:
                        yield from wait(warning_ready, "Actual partial warning tooltip", timeout=2.5)
                        valid_boxes = js("imageText.textBoxes.length", screenshot)
                        capture("partial")
                    finally:
                        QCoreApplication.sendEvent(window, QEvent(QEvent.Type.Leave))
                    js("onOcrGet({code:101,timestamp:1700000002,time:0.1,warnings:['NATIVE_UI_EMPTY_WARNING'],data:[]})", screenshot)
                    require(js("resultsTableView.getResult('',1700000002).warningText_", screenshot) == "NATIVE_UI_EMPTY_WARNING", "无文字警告丢失")
                    check("partial.results", rendered_row=row, clipboard_text=copied,
                          record_tab_index=js("tabPanel.currentIndex", screenshot), visible_record_text=record_visual,
                          actual_warning_tooltip=warning_visual,
                          valid_partial_overlay_boxes=valid_boxes, empty_result_overlay_boxes=js("imageText.textBoxes.length", screenshot),
                          notification_visual={"status": "NOT_RUN", "reason": "本驱动未截取系统通知窗口；记录/复制/叠加通过实际窗口验证"})
                    activate("GlobalConfigsPage")
                    capture("settings")
                    no_gpu()
                    self.active_check = "package_provenance"
                    provenance()
                    report["scenario_completed"] = True
                def begin():
                    if self.begun:
                        return
                    self.begun = True
                    self.steps = scenario()
                    scheduler.start_steps(self.steps, QTimer.singleShot, lambda: finish(), finish)
                window.frameSwapped.connect(lambda: QTimer.singleShot(0, begin) if not self.begun else None)
                window.show()
                QTimer.singleShot(15000, lambda: finish(AssertionError("未获得真实交互帧")) if not self.begun else None)
                QTimer.singleShot(240000, lambda: finish(AssertionError("原生场景总预算已用尽")) if not self.finished else None)
        QtQml.QQmlApplicationEngine = Engine
        from py_src.run import main as run_application
        require(Path(sys.modules["py_src.run"].__file__).resolve().is_relative_to(data), "启动入口来自包外")
        sys.argv = [str(root / "Umi-OCR.exe"), "--force"]
        try:
            run_application(str(root / "Umi-OCR.exe"), "./site-packages/PySide6/qml")
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise
        report["normal_exit"] = True
    except Exception as exc:
        report["errors"].append("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    finally:
        # 先销毁候选应用及其 QSettings，避免恢复之后再被析构写回覆盖。
        try:
            if previous_engine is not None:
                QtQml.QQmlApplicationEngine = previous_engine
            app = QApplication.instance() if "QApplication" in locals() else None
            if app is not None:
                for engine in engines:
                    engine.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                import shiboken6
                shiboken6.delete(app)
            report["settings_restored"] = snapshot.restore()
        except Exception as exc:
            report["errors"].append("配置恢复未完成：" + str(exc))
        if safety_finder in sys.meta_path:
            sys.meta_path.remove(safety_finder)
        if report["safety_blocks"]:
            check("no_gpu_runtime", "FAIL", reason="业务触发了安全门禁；没有实际执行模型", blocked=report["safety_blocks"])
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["acceptance"] = acceptance(report)
        write_new_json(output, report)
    if args.diagnose_language:
        failed = any(item["status"] == "FAIL" for item in report["checks"].values())
        return 0 if report.get("diagnostic_completed") and report["normal_exit"] and report["settings_restored"] and not report["errors"] and not failed else 2
    return 0 if report["acceptance"]["complete"] else 2


def campaign(args):
    root = checked_root(args.root)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    baseline = SettingsSnapshot(root / "UmiOCR-data").fingerprints()
    report = {"mode": "native-campaign", "root": str(root), "profile": args.profile,
              "input_sha256": package_inputs(root), "runs": [], "errors": [], "scenario_completed": False,
              "settings_before": baseline, "scope": "仅候选测试副本；不修改OS主题；不运行模型；不捕获桌面"}
    report["diagnostic_only"] = bool(args.diagnose_language)
    child = None
    boots = (("fresh", args.max_screenshots),) if args.diagnose_language else (("fresh", max(1, args.max_screenshots - 1)), ("saved-light", 1))
    for boot, limit in boots:
        child_output = output.with_name(output.stem + "-" + boot + ".json")
        log_path = child_output.with_suffix(".log")
        if child_output.exists() or log_path.exists():
            raise FileExistsError(child_output)
        command = [str(root / "UmiOCR-data/runtime/python.exe"), "-B", "-I", str(Path(__file__).resolve()),
                   "--root", str(root), "--output", str(child_output), "--profile", args.profile,
                   "--worker", "--boot", boot, "--max-screenshots", str(limit)]
        if args.diagnose_language:
            command += ["--diagnose-language", args.diagnose_language]
        with log_path.open("x", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                report["errors"].append(f"测试进程仍运行，未终止、未覆盖恢复配置，请正常退出候选窗口后检查；PID={process.pid}")
                report["active_pid"] = process.pid
                break
        child = json.loads(child_output.read_text(encoding="utf-8")) if child_output.is_file() else None
        report["runs"].append({"boot": boot, "command": command, "exit_code": code,
                               "report": str(child_output), "report_sha256": sha256(child_output) if child else None,
                               "log": str(log_path), "acceptance": child.get("acceptance") if child else None})
        complete = bool(child and (child.get("diagnostic_completed") if args.diagnose_language else child.get("scenario_completed") and child.get("acceptance", {}).get("complete")))
        if code or not child or not child.get("settings_restored") or not child.get("normal_exit") or not complete:
            report["errors"].append(f"{boot} 诊断/验收未通过，停止后续启动；不把正常首帧或进程退出当完整验收。")
            break
    report["scenario_completed"] = not args.diagnose_language and len(report["runs"]) == 2 and not report["errors"]
    report["diagnostic_completed"] = bool(args.diagnose_language and child and child.get("diagnostic_completed"))
    if "active_pid" not in report:
        report["settings_after"] = SettingsSnapshot(root / "UmiOCR-data").fingerprints()
        report["settings_restored"] = report["settings_after"] == baseline
        report["input_sha256_after"] = package_inputs(root)
        report["payload_unchanged"] = report["input_sha256_after"] == report["input_sha256"]
        if not report["payload_unchanged"]:
            report["errors"].append("所验源码或产物在运行期间变化，不能复用本轮验收。")
    else:
        report["settings_restored"] = False
    if args.diagnose_language:
        report["overall"] = "DIAGNOSTIC_COMPLETE" if report["diagnostic_completed"] and report["settings_restored"] and not report["errors"] else "DIAGNOSTIC_FAILED"
    else:
        report["overall"] = "PASS" if report["scenario_completed"] and report["settings_restored"] and not report["errors"] else "INCOMPLETE"
    write_new_json(output, report)
    print(json.dumps({"overall": report["overall"], "output": str(output), "runs": report["runs"]}, ensure_ascii=False))
    return 0 if report["overall"] in ("PASS", "DIAGNOSTIC_COMPLETE") else 2


def self_test(output):
    """纯标准库辅助检查；不导入 Qt、访问候选程序或启动任何子进程。"""
    scheduler = load_scheduler()
    passed, queue, actions, completed, failures = [], [], [], [], []
    def steps():
        actions.append("one")
        yield 1
        actions.append("two")
        yield 2
        actions.append("three")
    scheduler.start_steps(steps(), lambda delay, callback: queue.append((delay, callback)), lambda: completed.append(True), failures.append)
    assert not actions
    while queue:
        _delay, callback = queue.pop(0)
        callback()
    assert actions == ["one", "two", "three"] and completed == [True] and not failures
    passed.append("复用现有QTimer生成器调度器；每步归还调度，不提前标记完成")
    invalid_queue, invalid_failures, invalid_done = [], [], []
    scheduler.start_steps(iter([-1]), lambda delay, callback: invalid_queue.append(callback),
                          lambda: invalid_done.append(True), invalid_failures.append)
    invalid_queue.pop(0)()
    assert len(invalid_failures) == 1 and not invalid_done and not invalid_queue
    passed.append("调度异常不会继续执行或误标场景完整结束")
    ticks = iter([0, 1, 12])
    waiting = scheduler.wait_transition(lambda: False, timeout=12, clock=lambda: next(ticks))
    assert next(waiting) == 10
    try:
        next(waiting)
        raise AssertionError("应超时")
    except AssertionError as exc:
        assert "timed out" in str(exc)
    passed.append("等待保持原截止时间，不用循环processEvents或sleep掩盖未完成")
    report = {"checks": {}, "normal_exit": True, "scenario_completed": False, "settings_restored": True}
    assert not acceptance(report)["complete"]
    report["scenario_completed"] = True
    report["checks"]["unavailable"] = {"status": "NOT_RUN", "required": True}
    assert not acceptance(report)["complete"]
    report["checks"]["unavailable"]["required"] = False
    assert acceptance(report)["complete"]
    passed.append("正常退出不代替场景完成；必需NOT_RUN不冒充PASS")
    assert qml_error_status("file:///candidate/Configs.qml", 335) == "FAIL"
    assert qml_error_status("qrc:/qt_res/qml/Configs/Configs.qml", 335) == "FAIL"
    assert qml_error_status("", 0) == "NOT_RUN"
    passed.append("真实业务QML异常记FAIL，不再误归ProbeUnavailable；不可访问观测仍NOT_RUN")
    good = {"equal": True, "translated": True, "settled": True, "buttons_match": True}
    assert not sidebar_stable([good])
    assert not sidebar_stable([good, good, {**good, "equal": False}])
    assert not sidebar_stable([good, good, {**good, "buttons_match": False}])
    assert sidebar_stable([{"equal": False}, good, good, good])
    class VisualItem:
        def __init__(self, text=None, children=()):
            self.text, self.visual_children = text, children
        def childItems(self): return self.visual_children
        def metaObject(self): return self
        def indexOfProperty(self, name): return 0 if self.text is not None and name in ("text_", "bgPressColor_") else -1
        def property(self, name): return {"text_": self.text, "visible": True, "width": 100, "height": 40}[name]
    rendered = sidebar_buttons(VisualItem(children=[VisualItem(children=[VisualItem("one"), VisualItem("two")])]))
    assert [item["text"] for item in rendered] == ["one", "two"]
    assert sidebar_buttons(VisualItem()) == []
    passed.append("沿visual childItems读取Repeater委托；连续三次真实表/译文/按钮/排空全部收敛，不吞持续失败")
    options = [(aliases[0], name) for _canonical, aliases, name in LANGUAGES]
    chosen, bad = choose_languages(options)
    assert len(chosen) == 7 and not bad and all(item["code"] for item in chosen)
    assert choose_languages([("en_US", "英语")])[1]
    assert choose_languages([])[0][0]["code"] is None
    passed.append("七语别名和自身名称检查；缺失语言保持NOT_RUN")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-driver-selftest-", dir=REPO / "build/tmp") as directory:
        data = Path(directory)
        (data / ".settings").write_bytes(b"ORIGINAL\r\n")
        saved = SettingsSnapshot(data)
        (data / ".settings").write_bytes(b"MODIFIED")
        (data / "plugins").mkdir()
        (data / "plugins/.plugins_state").write_text("{}", encoding="utf-8")
        assert saved.restore()
        assert (data / ".settings").read_bytes() == b"ORIGINAL\r\n" and not (data / "plugins/.plugins_state").exists()
        assert sha256(data / ".settings") == hashlib.sha256(b"ORIGINAL\r\n").hexdigest()
        fixture = data / "build/staging/native-fixture"
        fixture_data = fixture / "UmiOCR-data"
        (fixture_data / "runtime").mkdir(parents=True)
        for path in (fixture / "Umi-OCR.exe", fixture_data / "main.py", fixture_data / "about.json", fixture_data / "runtime/python.exe"):
            path.write_bytes(b"SELFTEST_ONLY_NOT_EXECUTABLE")
        assert checked_root(fixture, repo=data) == fixture.resolve()
    passed.append("候选配置按原始字节恢复；原本不存在的测试配置移除；哈希可追溯")
    for rejected in (REPO, REPO / "release/Umi-OCR", REPO / "UmiOCR-data"):
        try:
            checked_root(rejected)
            raise AssertionError("错误接受正式目录")
        except ValueError:
            pass
    passed.append("拒绝正式release和源码目录，运行根仅接受build测试副本")
    try:
        checked_output(REPO / "release/native-driver.json")
        raise AssertionError("错误接受审计范围外的输出")
    except ValueError:
        pass
    passed.append("证据输出仅接受build/audit的新路径，不覆盖旧记录")
    assert not any(name == "PySide6" or name.startswith("PySide6.") for name in sys.modules)
    passed.append("辅助检查没有导入Qt、启动GUI/GPU或候选程序")
    result = {"mode": "driver-readiness-only", "passed": passed, "python": sys.version,
              "driver": str(Path(__file__).resolve()), "driver_sha256": sha256(__file__),
              "scheduler": str(Path(__file__).with_name("test_hot_ui.py")),
              "scheduler_sha256": sha256(Path(__file__).with_name("test_hot_ui.py")),
              "native_acceptance": {"status": "NOT_RUN", "reason": "等待主代理提供fresh候选root；没有运行原生窗口验收"}}
    write_new_json(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("base", "cuda-vl"), default="base")
    parser.add_argument("--max-screenshots", type=int, default=5)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--diagnose-language", choices=[item[0] for item in LANGUAGES], help="只做有限左栏时间序列诊断，不视为完整GUI验收")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--boot", choices=("fresh", "saved-light"), default="fresh", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        args.output = checked_output(args.output)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    if not 2 <= args.max_screenshots <= 8 and not args.worker:
        parser.error("max-screenshots须在2至8之间")
    if args.self_test:
        return self_test(args.output.resolve())
    if args.root is None:
        parser.error("原生运行必须提供--root；准备检查使用--self-test")
    if sys.platform != "win32":
        parser.error("原生窗口验收仅支持Windows")
    return native_worker(args) if args.worker else campaign(args)


if __name__ == "__main__":
    raise SystemExit(main())
