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
import site
import traceback


_DllDirectoryHandles = []


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
    for n in [".", "site-packages", "app.zip", "dependencies.zip", "app.zip/py_src/imports"]:  # 将模块目录添加到 Python 搜索路径中
        path = os.path.abspath(os.path.join(cwd, n))
        if os.path.exists(path) or ".zip/" in n:
            site.addsitedir(path)
    # Python 3.8+ 不再默认搜索依赖包的 DLL 子目录。这里只注册【基础包自己】
    # 需要的原生目录。
    #
    # Paddle 与 CUDA 的 DLL 目录曾经写死在这里，但那是基础包不应该知道的东西：
    # 它们属于 GPU OCR 插件的私有运行时，现在由插件清单的 runtime.dll_dirs
    # 声明、插件加载器在激活插件时挂载。基础包因此不再对任何 OCR 后端
    # 的目录布局有硬编码假设。
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        dllDirs = [
            os.path.join(cwd, "site-packages", "PySide6"),
        ]
        for path in dllDirs:
            if os.path.isdir(path):
                _DllDirectoryHandles.append(os.add_dll_directory(path))
    # 初始化Qt搜索路径为相对路径，避免上层目录存在中文编码
    os.environ.pop("QT_PLUGIN_PATH", None)
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.abspath("site-packages/PySide6/plugins/platforms")
    os.environ["QT_QPA_PLATFORM"] = "windows"
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.addLibraryPath("./site-packages/PySide6/plugins")


if __name__ == "__main__":
    try:
        initRuntimeEnvironment()  # 初始化运行环境
    except Exception:
        err = traceback.format_exc()
        from py_src.imports.umi_log import logger, Logs_Dir

        logger.critical(
            "Failed to initialize running environment!",
            exc_info=True,
            stack_info=True,
        )
        msg = f"Failed to initialize running environment!\n\n{err}\n\nSave the log file to: {Logs_Dir}"
        MessageBox(msg)
        sys.exit(0)
    try:
        # 获取 pystand.exe 记录的程序入口环境变量
        app_path = os.environ.get("PYSTAND", "")
        # 启动正式入口
        from py_src.run import main

        main(app_path=app_path, engineAddImportPath="./site-packages/PySide6/qml")
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
