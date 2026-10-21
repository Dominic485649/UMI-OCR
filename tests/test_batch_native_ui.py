"""在真实 Windows 应用窗口中验收 Explorer 拖入、队列鼠标操作和右键框选。"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import queue
import runpy
import socket
import subprocess
import sys
import threading
import time
import traceback

REPO = Path(__file__).resolve().parents[1]
PREFIX = "UMI_NATIVE_UI_JSON:"


def plain(value):
    if hasattr(value, "toVariant"):
        return plain(value.toVariant())
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def worker(args):
    """只在被验收的新副本中启动正式应用入口，Qt 操作全部留在主线程。"""
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    commands = queue.Queue()

    def emit(message):
        protocol.write(PREFIX + json.dumps(message, ensure_ascii=True) + "\n")
        protocol.flush()

    root = args.root.resolve()
    data = root / "UmiOCR-data"
    namespace = runpy.run_path(str(data / "main.py"), run_name="native_ui_runtime")
    namespace["initRuntimeEnvironment"]()
    os.MessageBox = lambda message, *unused: print(message, file=sys.stderr)
    from PySide6 import QtQml
    from PySide6.QtCore import QObject, QPointF, QTimer
    from PySide6.QtGui import QWindow
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtWidgets import QApplication
    opened = []
    submissions = []
    results = []
    result_lock = threading.Lock()
    Platform = MissionDOC = None
    original_open = original_add = original_task = None

    def traced_add(info, path, *values, **kwargs):
        submissions.append(str(path))
        return original_add(info, path, *values, **kwargs)

    def traced_task(info, page):
        value = original_task(info, page)
        with result_lock:
            results.append({"path": str(info.get("path", "")), "page": page,
                            "code": value.get("code"),
                            "blocks": len(value.get("data", [])) if isinstance(value.get("data"), list) else 0})
        return value

    original_engine = QtQml.QQmlApplicationEngine

    class Engine(original_engine):
        def load(self, *values):
            nonlocal Platform, MissionDOC, original_open, original_add, original_task
            # 正式 main 已建立自定义库路径和 umi_log，不能在其之前导入业务类。
            from py_src.platform import Platform
            from py_src.mission.mission_doc import MissionDOC
            original_open = Platform.startfile
            original_add = MissionDOC.addMission
            original_task = MissionDOC.msnTask
            # 只观察 OS 打开入口，不启动或关闭用户默认阅读器。
            Platform.startfile = lambda path: opened.append(str(path))
            MissionDOC.addMission = traced_add
            MissionDOC.msnTask = traced_task
            super().load(*values)
            if not self.rootObjects():
                raise RuntimeError("新候选没有创建真实 QML 窗口")
            window = self.rootObjects()[0]
            self.window = window
            self.ready = False
            self.page = None
            self.pump = QTimer(self)

            def evaluate(expression):
                expression_obj = QQmlExpression(QQmlEngine.contextForObject(window), window, expression)
                result = expression_obj.evaluate()
                if expression_obj.hasError():
                    raise RuntimeError(expression_obj.error().toString())
                if isinstance(result, tuple):
                    result = result[0]
                return plain(result)

            def item(name):
                candidates = window.findChildren(QObject, name)
                visible = [obj for obj in candidates if isinstance(obj, QQuickItem) and obj.isVisible()]
                if visible:
                    return visible[0]
                raise LookupError(f"没有可见的界面元素：{name}")

            def geometry(obj):
                owner = obj.window()
                point = obj.mapToScene(QPointF(0, 0))
                return {"hwnd": int(owner.winId()), "x": point.x(), "y": point.y(),
                        "width": obj.width(), "height": obj.height(),
                        "windowWidth": owner.width(), "windowHeight": owner.height(),
                        "enabled": obj.isEnabled(), "name": obj.objectName()}

            def setup():
                window.setVisibility(QWindow.Visibility.Windowed)
                window.show()
                evaluate("qmlapp.globalConfigs.setValue('ocr.api', 'win32_PaddleOCRv6_CUDA', true)")
                self.page = evaluate("qmlapp.tab.openTabPageByKey('BatchDOC')")
                self.page = window.findChild(QObject, "batchDocPage")
                if self.page is None:
                    raise RuntimeError("批量文档页面未实例化")
                # 候选是干净副本；仍检查后续硬件动作不能被意外启用。
                values = evaluate("qmlapp.tab.openTabPageByKey('BatchDOC').configsComp.getValueDict()")
                action = values.get("postTaskActions.system")
                if action not in (None, "", "none", "nothing", "doNothing", False, 0):
                    raise RuntimeError(f"测试副本存在非空闲后续系统动作：{action!r}")
                for key in values:
                    if key.startswith("mission.filesType."):
                        enabled = key.lower().endswith((".txt", ".csv"))
                        evaluate("qmlapp.tab.openTabPageByKey('BatchDOC').configsComp.setValue("
                                 + json.dumps(key) + "," + json.dumps(enabled) + ",true)")
                import importlib
                origins = {}
                for module_name in ("py_src.tag_pages.BatchDOC", "py_src.tag_pages.batch_runtime",
                                    "py_src.utils.file_finder", "py_src.utils.doc_probe"):
                    origin = str(importlib.import_module(module_name).__file__)
                    Path(origin).resolve().relative_to(data.resolve())
                    origins[module_name] = origin
                return {"hwnd": int(window.winId()), "width": window.width(), "height": window.height(),
                        "version": evaluate("UmiAbout.version.string"),
                        "moduleOrigins": origins, "postTaskAction": action}

            def preview_info(points=None):
                canvas = item("documentIgnoreAreaCanvas")
                preview = item("documentPreview")
                overlay = canvas.property("overlayLayer")
                converted = []
                for x, y in points or []:
                    point = overlay.mapToScene(QPointF(float(x), float(y)))
                    converted.append([point.x(), point.y()])
                return {"geometry": geometry(canvas), "imageWidth": canvas.property("imageSW"),
                        "imageHeight": canvas.property("imageSH"), "scale": canvas.property("scale"),
                        "boxes": plain(canvas.property("ig1Boxes")),
                        "textBoxes": plain(canvas.property("textBoxes")),
                        "ocrRunning": preview.property("ocrRunning"), "points": converted}

            def dispatch(message):
                command = message["command"]
                if command == "setup":
                    return setup()
                if command == "state":
                    return plain(self.page.property("backendState"))
                if command == "geometry":
                    return geometry(item(message["name"]))
                if command == "objects":
                    return [geometry(obj) for obj in window.findChildren(QQuickItem)
                            if obj.objectName().startswith(message["prefix"]) and obj.isVisible()]
                if command == "capture":
                    target = Path(message["path"]).resolve()
                    target.relative_to(args.output.resolve())
                    if target.exists() or not window.grabWindow().save(str(target)):
                        raise RuntimeError("窗口截图无法保存或目标已存在")
                    return str(target)
                if command == "opened":
                    return opened[:]
                if command == "submissions":
                    return submissions[:]
                if command == "results":
                    with result_lock:
                        return results[:]
                if command == "previewVisible":
                    preview = window.findChild(QObject, "documentPreview")
                    return bool(preview is not None and preview.property("visible"))
                if command == "previewInfo":
                    return preview_info(message.get("points"))
                if command == "previewOcr":
                    preview = item("documentPreview")
                    preview.setProperty("previewOCR", True)
                    preview.toPreview()
                    return True
                if command == "quit":
                    QApplication.instance().quit()
                    return True
                raise ValueError(f"未知测试命令：{command}")

            def drain():
                for _ in range(8):
                    try:
                        message = commands.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        value = dispatch(message)
                        emit({"id": message["id"], "ok": True, "value": value})
                    except Exception:
                        emit({"id": message["id"], "ok": False, "error": traceback.format_exc()})

            def first_frame():
                if self.ready:
                    return
                self.ready = True
                self.pump.timeout.connect(drain)
                self.pump.start(15)
                emit({"event": "ready", "hwnd": int(window.winId())})

            window.frameSwapped.connect(first_frame)
            QTimer.singleShot(25000, lambda: QApplication.instance().quit() if not self.ready else None)

    def input_reader():
        for line in sys.stdin:
            try:
                commands.put(json.loads(line))
            except Exception:
                emit({"event": "protocol-error", "error": traceback.format_exc()})
        commands.put({"id": -1, "command": "quit"})

    QtQml.QQmlApplicationEngine = Engine
    threading.Thread(target=input_reader, daemon=True).start()
    sys.argv = [str(root / "Umi-OCR.exe"), "--force"]
    try:
        from py_src.run import main
        main(str(root / "Umi-OCR.exe"), "./site-packages/PySide6/qml")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
    finally:
        if Platform is not None:
            Platform.startfile = original_open
        if MissionDOC is not None:
            MissionDOC.addMission = original_add
            MissionDOC.msnTask = original_task


class Client:
    def __init__(self, root, output):
        self.responses = queue.Queue()
        self.sequence = 0
        self.tail = []
        self.log = (output / "application-stderr.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [str(root / "UmiOCR-data/runtime/python.exe"), "-I", "-B", str(Path(__file__).resolve()),
             str(root), "--output", str(output), "--worker"],
            cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            text=True, encoding="utf-8", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        def read():
            for line in self.process.stdout:
                if line.startswith(PREFIX):
                    try:
                        self.responses.put(json.loads(line[len(PREFIX):]))
                    except ValueError:
                        self.tail.append(line[-500:])
                else:
                    self.tail.append(line[-500:])
                    self.tail[:] = self.tail[-20:]
            self.responses.put({"event": "eof"})

        threading.Thread(target=read, daemon=True).start()
        try:
            ready = self.responses.get(timeout=40)
            if ready.get("event") != "ready":
                raise RuntimeError(f"应用首帧失败：{ready}; {self.tail}")
        except BaseException:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=20)
            self.log.close()
            raise

    def call(self, command, **values):
        self.sequence += 1
        request_id = self.sequence
        self.process.stdin.write(json.dumps({"id": request_id, "command": command, **values}, ensure_ascii=True) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + 30
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Qt 主线程命令超时：{command}")
            try:
                response = self.responses.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"Qt 主线程命令超时：{command}; {self.tail}") from exc
            if response.get("event") == "eof":
                raise RuntimeError(f"测试应用提前退出：{self.process.poll()}; {self.tail}")
            if response.get("id") != request_id:
                continue
            if not response["ok"]:
                raise RuntimeError(response["error"])
            return response.get("value")

    def wait(self, predicate, timeout=60):
        deadline = time.monotonic() + timeout
        state = None
        while time.monotonic() < deadline:
            state = self.call("state")
            if predicate(state):
                return state
            time.sleep(.05)
        raise TimeoutError(f"真实界面状态未在期限内满足：{json.dumps(state, ensure_ascii=False)[:2500]}")

    def close(self):
        try:
            if self.process.poll() is None:
                try:
                    self.call("quit")
                    self.process.wait(timeout=30)
                except Exception as exc:
                    # 只结束自己的回归子进程，且强制收尾必须让验收失败。
                    self.process.terminate()
                    self.process.wait(timeout=20)
                    raise RuntimeError("测试应用未能正常退出，已仅清理本回归子进程") from exc
            if self.process.returncode != 0:
                raise RuntimeError(f"测试应用异常退出：{self.process.returncode}")
            return self.process.returncode
        finally:
            self.log.close()


class NativeInput:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, wintypes.UINT]
        try:
            self.user.SetThreadDpiAwarenessContext.argtypes = [wintypes.HANDLE]
            self.user.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
            self.user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            pass

    def focus(self, hwnd):
        self.user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.WindowFromPoint.argtypes = [wintypes.POINT]
        self.user.WindowFromPoint.restype = wintypes.HWND
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                          wintypes.UINT, wintypes.UINT, wintypes.UINT]
        message = wintypes.MSG()
        self.user.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        self.user.ShowWindow(wintypes.HWND(hwnd), 9)
        self.user.SetForegroundWindow(wintypes.HWND(hwnd))
        if int(self.user.GetForegroundWindow() or 0) != hwnd:
            foreground = self.user.GetForegroundWindow()
            target_thread = self.user.GetWindowThreadProcessId(foreground, None)
            current_thread = self.kernel.GetCurrentThreadId()
            if target_thread and target_thread != current_thread:
                attached = self.user.AttachThreadInput(current_thread, target_thread, True)
                try:
                    self.user.SetForegroundWindow(wintypes.HWND(hwnd))
                finally:
                    if attached:
                        self.user.AttachThreadInput(current_thread, target_thread, False)
        if int(self.user.GetForegroundWindow() or 0) != hwnd:
            # Windows 可拒绝后台进程直接置前。只在命中测试窗口自己的
            # 标题栏时发送一次真实点击，不改系统策略，不向遮挡它的窗口输入。
            rectangle = wintypes.RECT()
            self.user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            was_topmost = bool(self.user.GetWindowLongW(wintypes.HWND(hwnd), -20) & 8)
            try:
                # 仅暂时置顶测试自己的窗口，让安全命中检查不受其它窗口遮挡。
                self.user.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0, 0x0053)
                if not self.user.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rectangle)):
                    raise ctypes.WinError(ctypes.get_last_error())
                point = wintypes.POINT((rectangle.left + rectangle.right) // 2, rectangle.top + 12)
                hit = self.user.WindowFromPoint(point)
                expected_root = self.user.GetAncestor(wintypes.HWND(hwnd), 2)
                if hit and self.user.GetAncestor(hit, 2) == expected_root:
                    self.move_pointer(point.x, point.y)
                    self.user.mouse_event(0x0002, 0, 0, 0, 0)
                    self.user.mouse_event(0x0004, 0, 0, 0, 0)
                    deadline = time.monotonic() + .5
                    while int(self.user.GetForegroundWindow() or 0) != hwnd and time.monotonic() < deadline:
                        time.sleep(.01)
            finally:
                if not was_topmost:
                    self.user.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-2), 0, 0, 0, 0, 0x0053)
        if int(self.user.GetForegroundWindow() or 0) != hwnd:
            raise RuntimeError(f"无法置前测试窗口 {hwnd}，当前前台 {int(self.user.GetForegroundWindow() or 0)}；未向其它窗口发送输入")

    def position(self, hwnd, x, y, width, height):
        if not self.user.SetWindowPos(wintypes.HWND(hwnd), None, x, y, width, height, 0x0040):
            raise ctypes.WinError(ctypes.get_last_error())

    def point(self, geometry, fraction=(.5, .5), scene_point=None):
        hwnd = int(geometry["hwnd"])
        rect = wintypes.RECT()
        origin = wintypes.POINT(0, 0)
        if not self.user.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.user.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin))
        if scene_point is None:
            x = geometry["x"] + geometry["width"] * fraction[0]
            y = geometry["y"] + geometry["height"] * fraction[1]
        else:
            x, y = scene_point
        return (round(origin.x + x * rect.right / geometry["windowWidth"]),
                round(origin.y + y * rect.bottom / geometry["windowHeight"]))

    def move_pointer(self, x, y):
        x, y = int(x), int(y)
        if not self.user.SetCursorPos(x, y):
            raise ctypes.WinError(ctypes.get_last_error())
        self.user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        actual = wintypes.POINT()
        if not self.user.GetCursorPos(ctypes.byref(actual)) or (actual.x, actual.y) != (x, y):
            raise RuntimeError("系统未将鼠标定位到指定测试坐标，停止输入")

    def click_at(self, hwnd, point, button="left"):
        self.focus(hwnd)
        self.move_pointer(*point)
        down, up = (0x0002, 0x0004) if button == "left" else (0x0008, 0x0010)
        self.user.mouse_event(down, 0, 0, 0, 0)
        self.user.mouse_event(up, 0, 0, 0, 0)

    def click(self, client, name, button="left", fraction=(.5, .5)):
        geometry = client.call("geometry", name=name)
        if not geometry["enabled"]:
            raise RuntimeError(f"目标交互当前禁用：{name}")
        self.click_at(int(geometry["hwnd"]), self.point(geometry, fraction), button)

    def drag(self, hwnd, start, end, button="left"):
        self.focus(hwnd)
        self.move_pointer(*start)
        down, up = (0x0002, 0x0004) if button == "left" else (0x0008, 0x0010)
        self.user.mouse_event(down, 0, 0, 0, 0)
        try:
            for step in range(1, 26):
                t = step / 25
                self.move_pointer(round(start[0] + (end[0] - start[0]) * t),
                                       round(start[1] + (end[1] - start[1]) * t))
                # 系统拖动需要真实时间展开，不能把所有坐标压到一次事件循环。
                time.sleep(.018)
        finally:
            self.user.mouse_event(up, 0, 0, 0, 0)

    def escape(self, hwnd):
        self.focus(hwnd)
        self.user.keybd_event(0x1B, 0, 0, 0)
        self.user.keybd_event(0x1B, 0, 0x0002, 0)


def explorer(action, folder, **values):
    command = ["pwsh", "-NoLogo", "-NoProfile", "-STA", "-File", str(REPO / "tests/native_batch_input.ps1"),
               "-Action", action, "-Folder", str(folder)]
    for key, value in values.items():
        command.extend(["-" + key, str(value)])
    result = subprocess.run(command, cwd=REPO, text=True, encoding="utf-8",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f"Windows 原生界面辅助失败：{result.stderr[-1800:]}")
    lines = [line for line in result.stdout.splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError("Windows 原生界面辅助没有返回坐标证据")
    return json.loads(lines[-1])


def make_inputs(root, folder):
    namespace = runpy.run_path(str(root / "UmiOCR-data/main.py"), run_name="native_fixture_runtime")
    namespace["initRuntimeEnvironment"]()
    from PIL import Image, ImageDraw, ImageFont
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    font_path = next((path for path in (font_dir / "msyh.ttc", font_dir / "arial.ttf") if path.is_file()), None)
    font = ImageFont.truetype(str(font_path), 72) if font_path else ImageFont.load_default()
    nested = folder / "待处理 目录"
    nested.mkdir()
    paths = {}
    for letter, pages in (("A", 12), ("B", 1), ("C", 1), ("D", 1)):
        image = Image.new("RGB", (1000, 260), "white")
        ImageDraw.Draw(image).text((40, 75), f"UMI OCR QUEUE {letter} 302", font=font, fill="black")
        path = (nested if letter == "D" else folder) / f"queue {letter}.pdf"
        image.save(path, "PDF", save_all=True, append_images=[image] * (pages - 1), resolution=72)
        image.close()
        paths[letter] = path.resolve()
    return paths, nested


def find_row(state, path):
    key = os.path.normcase(os.path.abspath(path))
    return next((row for row in state.get("rows", [])
                 if os.path.normcase(os.path.abspath(row["path"])) == key), None)


def driver(args):
    if os.name != "nt":
        raise RuntimeError("此回归要求真实 Windows 桌面")
    root = args.root.resolve()
    root.relative_to(REPO.resolve())
    if not (root / "Umi-OCR.exe").is_file() or not (root / "UmiOCR-data/runtime/python.exe").is_file():
        raise RuntimeError("只能对本项目的新完整程序副本执行原生界面回归")
    output = args.output.resolve()
    output.relative_to((REPO / "build").resolve())
    if output.exists():
        raise RuntimeError("原生回归必须使用新的输出目录")
    output.mkdir(parents=True)
    version = json.loads((root / "UmiOCR-data/about.json").read_text("utf-8"))["version"]
    if [version[key] for key in ("major", "minor", "patch")] != [3, 0, 3]:
        raise RuntimeError("不允许把旧版本窗口当作本次验证对象")
    folder = output / "合成 输入"
    folder.mkdir()
    paths, nested = make_inputs(root, folder)
    settings = root / "UmiOCR-data/.settings"
    pre = root / "UmiOCR-data/.pre_settings"
    saved = {path: path.read_bytes() if path.exists() else None for path in (settings, pre)}
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    client = None
    opened_explorer = False
    report = {"status": "RUNNING", "root": str(root), "cases": {}, "scope": "native Windows inputs in real application"}
    try:
        settings.write_text("[Global]\nwindow.startupInvisible=false\nserver.enable=false\n"
                            f"server.host=127.0.0.1\nserver.port={port}\n", encoding="utf-8")
        pre.write_text(json.dumps({"i18n": "", "opengl": "d3d11", "server_port": port,
                                   "last_pid": -1, "last_ptime": -1}), encoding="utf-8")
        client = Client(root, output)
        setup = client.call("setup")
        assert setup["version"] == "3.0.3", setup
        report["application"] = setup
        native = NativeInput()
        work = wintypes.RECT()
        native.user.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)
        width, height = work.right - work.left, work.bottom - work.top
        split = max(480, round(width * .34))
        native.position(int(setup["hwnd"]), work.left + split, work.top,
                        width - split, height)
        source = explorer("ensure", folder)
        opened_explorer = True
        native.position(int(source["hwnd"]), work.left, work.top, split - 12, height)
        client.call("capture", path=str(output / "01-ready.png"))

        def drop(names):
            native.focus(int(source["hwnd"]))
            selected = explorer("select", folder, NamesJson=json.dumps(names, ensure_ascii=False))
            target = client.call("geometry", name="batchDocFilesTable")
            native.drag(int(source["hwnd"]), (round(selected["x"]), round(selected["y"])),
                        native.point(target, (.55, .42)))
            return selected

        # 外部拖入是真正 Explorer 的 OLE 拖动，不构造 Qt 拖放事件。
        selection = drop([paths["A"].name])
        client.wait(lambda state: find_row(state, paths["A"]) is not None and not state.get("importCount"))
        report["cases"]["explorer_idle_file"] = {"status": "PASS", "selection": selection["kind"]}

        native.click(client, "filesOpenButton")
        dialog = explorer("dialog", folder, ApplicationPid=client.process.pid, FilePath=paths["B"])
        native.click_at(int(dialog["hwnd"]), (round(dialog["x"]), round(dialog["y"])))
        client.wait(lambda state: find_row(state, paths["B"]) is not None and not state.get("importCount"))
        report["cases"]["native_open_dialog"] = {"status": "PASS"}
        native.click(client, "missionStartButton")
        client.wait(lambda state: bool(state.get("activeId")), timeout=60)
        native.click(client, "missionPauseResumeButton")
        client.wait(lambda state: state.get("paused") is True)
        drop([paths["C"].name, nested.name])
        state = client.wait(lambda value: find_row(value, paths["D"]) is not None
                            and find_row(value, paths["C"]) is not None and not value.get("importCount"))
        assert state["paused"] and len(state["rows"]) == 4, state
        report["cases"]["explorer_paused_multifile_folder"] = {"status": "PASS"}

        row_d = find_row(state, paths["D"])
        row_b = find_row(state, paths["B"])
        d_geometry = client.call("geometry", name="fileRowMouse:" + row_d["path"])
        b_geometry = client.call("geometry", name="fileRowMouse:" + row_b["path"])
        native.drag(int(d_geometry["hwnd"]), native.point(d_geometry, (.55, .5)),
                    native.point(b_geometry, (.55, .2)))
        state = client.wait(lambda value: value.get("pending", [None])[0] == row_d["id"])
        row_c = find_row(state, paths["C"])
        native.click(client, "fileRowMouse:" + row_c["path"], "right")
        native.click(client, "docRemoveAction")
        state = client.wait(lambda value: find_row(value, paths["C"]) is None)
        assert state["donePages"] <= state["totalPages"] and state["totalPages"] == 14, state
        assert [entry for entry in state["pending"]] == [row_d["id"], row_b["id"]], state
        assert paths["C"].is_file()
        client.call("capture", path=str(output / "02-paused-sorted-removed.png"))
        report["cases"]["native_sort_remove_live_counts"] = {"status": "PASS", "totalPages": state["totalPages"]}
        native.click(client, "missionPauseResumeButton")
        state = client.wait(lambda value: value.get("completed") and not value.get("running"), timeout=240)
        assert state["failedDocs"] == 0, state
        expected = [str(paths[key]).replace("\\", "/") for key in ("A", "D", "B")]
        submitted = client.call("submissions")
        assert [os.path.normcase(os.path.abspath(path)) for path in submitted[:3]] == [
            os.path.normcase(os.path.abspath(path)) for path in expected], submitted
        report["cases"]["actual_dispatch_order"] = {"status": "PASS", "paths": expected}

        row_b = find_row(state, paths["B"])
        old_paths = [Path(artifact["path"]) for artifact in row_b["artifacts"] if artifact.get("openable")]
        assert old_paths, row_b
        old_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in old_paths}
        native.click(client, "fileRowMouse:" + row_b["path"], "right")
        native.click(client, "docOpenOriginalAction")
        assert os.path.normcase(client.call("opened")[-1]) == os.path.normcase(str(paths["B"])), client.call("opened")
        native.click(client, "fileRowMouse:" + row_b["path"], "right")
        native.click(client, "docOpenArtifactsAction")
        artifact_items = client.call("objects", prefix="docArtifactAction:")
        if artifact_items:
            client.call("capture", path=str(output / "03-output-menu.png"))
            native.click(client, artifact_items[0]["name"])
        assert any(os.path.normcase(path) == os.path.normcase(client.call("opened")[-1]) for path in old_hashes)
        report["cases"]["native_context_open_dispatch"] = {"status": "PASS", "osAssociation": "SPY_ONLY"}

        native.click(client, "fileRowMouse:" + row_b["path"], "right")
        native.click(client, "docReocrAction")
        client.wait(lambda value: value.get("running"))
        state = client.wait(lambda value: value.get("completed") and not value.get("running"), timeout=150)
        assert state["failedDocs"] == 0 and state["totalDocs"] == 1, state
        for path, checksum in old_hashes.items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == checksum, path
        row_b = find_row(state, paths["B"])
        assert all(artifact["path"] not in old_hashes for artifact in row_b["artifacts"]), row_b
        assert len(client.call("submissions")) == 4, client.call("submissions")
        report["cases"]["native_single_reocr_preserves_previous"] = {"status": "PASS"}

        native.click(client, "fileRowMouse:" + row_b["path"])
        deadline = time.monotonic() + 90
        while True:
            try:
                info = client.call("previewInfo")
                if info["imageWidth"] and info["imageHeight"]:
                    break
            except RuntimeError:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError("文档预览未显示有效图像")
            time.sleep(.05)
        client.call("previewOcr")
        deadline = time.monotonic() + 90
        while True:
            info = client.call("previewInfo")
            if not info["ocrRunning"] and info["textBoxes"]:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("未获得用于忽略区域验收的实际 OCR 文本")
            time.sleep(.1)
        source_points = [[info["imageWidth"] * .005, info["imageHeight"] * .005],
                         [info["imageWidth"] * .995, info["imageHeight"] * .995]]
        info = client.call("previewInfo", points=source_points)
        native.drag(int(info["geometry"]["hwnd"]),
                    native.point(info["geometry"], scene_point=info["points"][0]),
                    native.point(info["geometry"], scene_point=info["points"][1]), "right")
        info = client.call("previewInfo")
        assert len(info["boxes"]) == 1, info
        box = info["boxes"][0]
        assert box["width"] > 0 and box["height"] > 0, box
        client.call("capture", path=str(output / "04-native-ignore-region.png"))
        previous_count = len(client.call("results"))
        client.call("previewOcr")
        deadline = time.monotonic() + 90
        while True:
            values = client.call("results")
            info = client.call("previewInfo")
            if len(values) > previous_count and not info["ocrRunning"]:
                assert values[-1]["code"] == 101 and values[-1]["blocks"] == 0, values[-1]
                break
            if time.monotonic() > deadline:
                raise TimeoutError("当前右键区域未在实际预览 OCR 中得到验证")
            time.sleep(.1)
        native.escape(int(info["geometry"]["hwnd"]))
        deadline = time.monotonic() + 10
        while client.call("previewVisible"):
            if time.monotonic() > deadline:
                raise TimeoutError("原生 Esc 未完成文档预览的保存返回")
            time.sleep(.05)
        saved_state = client.wait(lambda value: bool(find_row(value, paths["B"]).get("argd", {}).get("tbpu.ignoreArea")), timeout=10)
        report["cases"]["native_right_drag_and_actual_ignore_filter"] = {"status": "PASS", "boxes": info["boxes"]}
        report["cases"]["native_escape_saves_ignore_configuration"] = {"status": "PASS"}
        client.call("capture", path=str(output / "05-complete.png"))
        report["finalState"] = {key: state.get(key) for key in
                                ("totalDocs", "doneDocs", "successDocs", "failedDocs", "totalPages", "donePages")}
        report["status"] = "PASS"
    except Exception:
        report["status"] = "FAIL"
        report["error"] = traceback.format_exc()
        if client and client.process.poll() is None:
            try:
                client.call("capture", path=str(output / "failure.png"))
            except Exception:
                pass
        raise
    finally:
        if client:
            try:
                report["applicationExitCode"] = client.close()
            except Exception as exc:
                report.setdefault("cleanupErrors", []).append(str(exc))
                report["status"] = "FAIL"
        if opened_explorer:
            try:
                explorer("close", folder)
            except Exception as exc:
                report["explorerClose"] = str(exc)
        for path, content in saved.items():
            try:
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
            except Exception as exc:
                report.setdefault("cleanupErrors", []).append(str(exc))
                report["status"] = "FAIL"
        (output / "native-ui-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "cases": report["cases"],
                          "report": str(output / "native-ui-report.json")}, ensure_ascii=False))
    if report["status"] != "PASS":
        raise RuntimeError("原生回归未通过或测试副本未能正确收尾，详见回执")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    arguments = parser.parse_args()
    worker(arguments) if arguments.worker else driver(arguments)
