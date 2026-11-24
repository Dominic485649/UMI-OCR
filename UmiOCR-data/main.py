# Umi-OCR
# OCR software, free and offline. 开源、免费的离线OCR软件。
# Website - https://github.com/hiroi-sora/Umi-OCR
# Author - hiroi-sora
#
# You are free to use, modify, and distribute Umi-OCR, but it must include
# the original author's copyright statement and the following license statement.
# 您可以免费地使用、修改和分发 Umi-OCR ，但必须包含原始作者的版权声明和下列许可声明。
"""
Copyright (c) 2023 hiroi-sora

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


"""
======================================================
========== Umi-OCR Windows 运行环境初始化入口 ==========
======================================================

说明：
本文件负责 Windows + PyStand 运行环境的初始化，主要涉及：
- 创建底层弹窗接口 os.MessageBox
- 重定向标准输入输出流
- 指定工作目录为 "/UmiOCR-data"
- 添加Python库搜索目录 "site-packages"
- 添加PySide6插件搜索目录 "PySide6/plugins"

环境初始化后，调用正式入口 py_src/run.py 启动软件。

耗时分析：
runtime/python.exe -X importtime main.py
"""


import os
import sys
from pathlib import Path
import traceback


_DllDirectoryHandles = []


def configureUtf8():
    """统一标准流和普通 Python 子进程的编码，不依赖系统代码页。"""
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(
                encoding="utf-8", errors=getattr(stream, "errors", None) or "strict"
            )


def installNoConsoleSubprocess():
    """Keep console helpers launched by dependencies hidden in the GUI build."""
    if os.name != "nt":
        return
    import subprocess

    if getattr(subprocess.Popen, "_umi_no_console", False):
        return
    original = subprocess.Popen

    class NoConsolePopen(original):
        _umi_no_console = True

        def __init__(self, *args, **kwargs):
            if not kwargs.get("creationflags"):
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = NoConsolePopen


def MessageBox(msg, type_="error"):
    # 软件中如遇到错误，会优先用QT弹窗来警示。
    # 但一些异常可能触发太早或导致QT事件循环崩溃。
    # 因此 os.MessageBox() 是用于报告错误的最后防线。
    info = "Umi-OCR Message"
    if type_ == "error":
        info = "【错误】 Umi-OCR Error"
    elif type_ == "warning":
        info = "【警告】 Umi-OCR Warning"
    try:
        # 通过 ctypes 发起弹窗
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, str(msg), str(info), 0)
    except Exception:
        # GUI 发行版永不创建控制台窗口；保留相对路径诊断文件。
        try:
            with open("startup_error.log", "a", encoding="utf-8") as stream:
                stream.write(f"{info}: {msg}\n")
        except OSError:
            pass
    return 0


os.MessageBox = MessageBox


def initRuntimeEnvironment():
    """初始化运行环境"""

    configureUtf8()
    installNoConsoleSubprocess()

    # 尝试获取控制台的输出对象
    try:
        fd = os.open("CONOUT$", os.O_RDWR | os.O_BINARY)
        fp = os.fdopen(fd, "w", encoding="utf-8")
    except Exception as e:
        fp = open(os.devnull, "w", encoding="utf-8")
    # 输出流不存在时，重定向到控制台
    if not sys.stdout:
        sys.stdout = fp
    if not sys.stderr:
        sys.stderr = fp
    # def except_hook(cls, exception, traceback):
    #     sys.__excepthook__(cls, exception, traceback)
    # sys.excepthook = except_hook

    # 初始化工作目录和Python搜索路径
    script = os.path.abspath(__file__)  # 启动脚本.py的路径
    cwd = os.path.dirname(script)  # 工作目录
    os.chdir(cwd)  # 重新设定工作目录（不在最顶层，而在 UmiOCR-data 文件夹下）
    if cwd in sys.path:
        sys.path.remove(cwd)
    sys.path.insert(0, cwd)
    sys.dont_write_bytecode = True  # 正式运行组只读，不写 __pycache__。
    # 先独立核对原有容器与本体通用组；添加显式路径，不执行 .pth。
    from runtime_archive_bootstrap import prepare_archives
    from shared_runtime_bootstrap import dll_paths, host_groups

    archivePaths = prepare_archives(cwd, kind="host")
    groups = host_groups(cwd, [Path(path) for path in archivePaths])
    paths = [*archivePaths, *(str(group.site) for group in groups)]
    for path in paths:
        if path in sys.path:
            sys.path.remove(path)
    sys.path[0:0] = paths
    for n in ("site-packages", "app.zip/py_src/imports"):
        path = os.path.abspath(os.path.join(cwd, n))
        if (os.path.isdir(path) or ".zip/" in n and archivePaths) and path not in sys.path:
            sys.path.append(path)
    # 本体只注册自身 Qt 和通用组，不挂载 Paddle、NVIDIA 或任一插件根。
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        qt = Path(cwd) / "site-packages/PySide6"
        for path in dll_paths(groups, private=(qt,) if qt.is_dir() else ()):
            _DllDirectoryHandles.append(os.add_dll_directory(str(path)))
    # 初始化Qt搜索路径为相对路径，避免上层目录存在中文编码
    os.environ.pop("QT_PLUGIN_PATH", None)
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.abspath("site-packages/PySide6/plugins/platforms")
    os.environ["QT_QPA_PLATFORM"] = "windows"
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.addLibraryPath("./site-packages/PySide6/plugins")


if __name__ == "__main__":
    # Disabled by default: do not import or initialize the observer on normal runs.
    startupTrace = None
    traceRequested = bool(os.environ.get("UMI_STARTUP_TRACE"))
    if traceRequested:
        import time
        startupEntryNs = time.perf_counter_ns()
    try:
        initRuntimeEnvironment()  # 初始化运行环境
        if traceRequested:
            bootstrapDoneNs = time.perf_counter_ns()
            from py_src.utils.startup_trace import from_environment
            startupTrace = from_environment()
            startupTrace.mark("python-entry", at_ns=startupEntryNs)
            startupTrace.mark("S1", at_ns=bootstrapDoneNs, origin="runtime-environment-ready")
    except Exception:
        err = traceback.format_exc()
        msg = f"Failed to initialize running environment!\n\n{err}"
        # 启动依赖验证可能早于 app.zip 挂载；此时不能依赖其中的日志模块来报错。
        try:
            from py_src.imports.umi_log import logger, Logs_Dir

            logger.critical("Failed to initialize running environment!", exc_info=True, stack_info=True)
            msg += f"\n\nSave the log file to: {Logs_Dir}"
        except ImportError:
            pass
        MessageBox(msg)
        sys.exit(0)
    try:
        # 获取 pystand.exe 记录的程序入口环境变量
        app_path = os.environ.get("PYSTAND", "")
        # 启动正式入口
        from py_src.run import main

        main(app_path=app_path, engineAddImportPath="./site-packages/PySide6/qml", startupTrace=startupTrace)
    except Exception:
        err = traceback.format_exc()
        from py_src.imports.umi_log import logger, Logs_Dir

        logger.critical(
            "Failed to startup main program!",
            exc_info=True,
            stack_info=True,
        )
        msg = f"Failed to startup main program!\n\n{err}\n\nSave the log file to: {Logs_Dir}"
        MessageBox(msg)
        sys.exit(0)
