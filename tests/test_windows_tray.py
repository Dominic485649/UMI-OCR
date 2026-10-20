"""Verify the candidate's actual notification icon registered with Windows Shell."""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("guidItem", GUID)]


def shell_icons(pid):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    shell32.Shell_NotifyIconGetRect.argtypes = [ctypes.POINTER(NOTIFYICONIDENTIFIER), ctypes.POINTER(wintypes.RECT)]
    shell32.Shell_NotifyIconGetRect.restype = ctypes.c_long
    results = []

    @callback_type
    def inspect(hwnd, _):
        window_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value != pid:
            return True
        name = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, name, len(name))
        # Qt's Windows tray implementation creates a hidden top-level message
        # window and uses notify-icon id zero.  We query the Shell, not QML's
        # visible property, so a declared but unregistered icon cannot pass.
        if name.value != "QTrayIconMessageWindow":
            return True
        identifier = NOTIFYICONIDENTIFIER()
        identifier.cbSize = ctypes.sizeof(identifier)
        identifier.hWnd = hwnd
        identifier.uID = 0
        rect = wintypes.RECT()
        hresult = shell32.Shell_NotifyIconGetRect(ctypes.byref(identifier), ctypes.byref(rect))
        if hresult >= 0 and rect.right > rect.left and rect.bottom > rect.top:
            results.append({"window": name.value, "rect": [rect.left, rect.top, rect.right, rect.bottom]})
        return True

    user32.EnumWindows(inspect, 0)
    return results


def wait_http_ready(opener, base_url, process, expected_version, timeout=30):
    """退出之前实际读取服务标识，不把退出接口的应答当作先前已就绪。"""
    import re

    deadline = time.monotonic() + timeout
    last_error = "no response"
    attempts = 0
    while True:
        if process.poll() is not None:
            raise RuntimeError("Candidate exited before HTTP readiness")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("HTTP readiness timed out: " + last_error)
        attempts += 1
        try:
            with opener.open(base_url + "/umiocr", timeout=min(2, remaining)) as response:
                identity = response.read(4096).decode("utf-8").strip()
                if response.status != 200 or not identity.startswith("Umi-OCR") or not re.search(
                    r"(?<![A-Za-z0-9.])v?" + re.escape(expected_version) + r"(?![A-Za-z0-9.])", identity
                ):
                    raise RuntimeError("Unexpected Umi-OCR HTTP identity: " + identity[:160])
                return {"ready": True, "status": response.status,
                        "identity": identity, "attempts": attempts}
        except (urllib.error.URLError, OSError) as exc:
            last_error = str(exc)
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("staging_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("Actual Windows Shell validation requires Windows")
    root = args.staging_root.resolve()
    output = args.output.resolve()
    if output.exists() or not output.parent.is_dir():
        raise RuntimeError("Use a new report path in an existing output directory")
    data = root / "UmiOCR-data"
    version = json.loads((data / "about.json").read_text(encoding="utf-8"))["version"]
    expected_version = ".".join(str(version[key]) for key in ("major", "minor", "patch"))
    settings = data / ".settings"
    previous_settings = settings.read_bytes() if settings.exists() else None
    pre_settings = data / ".pre_settings"
    previous_pre = pre_settings.read_bytes() if pre_settings.exists() else None
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = None
    try:
        settings.write_text(
            "[Global]\nwindow.startupInvisible=true\nserver.enable=true\n"
            f"server.host=127.0.0.1\nserver.port={port}\n", encoding="utf-8",
        )
        pre_settings.write_text(json.dumps({"i18n": "", "opengl": "d3d11", "server_port": port,
                                            "last_pid": -1, "last_ptime": -1}), encoding="utf-8")
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen([str(root / "Umi-OCR.exe"), "--force"], cwd=root,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 45
            icons = []
            while not icons:
                if process.poll() is not None:
                    raise RuntimeError(f"Candidate exited before Shell tray registration: {process.returncode}")
                icons = shell_icons(process.pid)
                if time.monotonic() >= deadline:
                    raise TimeoutError("Candidate did not register an actual Windows notification icon")
                if not icons:
                    time.sleep(0.1)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            readiness = wait_http_ready(opener, f"http://127.0.0.1:{port}", process, expected_version)
            request = urllib.request.Request(f"http://127.0.0.1:{port}/argv",
                data=b'["--quit"]', headers={"Content-Type": "application/json"})
            with opener.open(request, timeout=30) as response:
                reply = response.read().decode("utf-8")
            process.wait(timeout=20)
            assert process.returncode == 0, process.returncode
            output.write_text(json.dumps({"status": "PASS", "pid": process.pid,
                "shell_icons": icons, "http_ready_before_quit": readiness["ready"],
                "http_readiness": readiness, "quit_reply": reply,
                "exit_code": process.returncode}, indent=2) + "\n", encoding="utf-8")
            print("Actual Windows Shell registration, pre-quit HTTP readiness and clean quit passed.")
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        if previous_settings is None:
            settings.unlink(missing_ok=True)
        else:
            settings.write_bytes(previous_settings)
        if previous_pre is None:
            pre_settings.unlink(missing_ok=True)
        else:
            pre_settings.write_bytes(previous_pre)


if __name__ == "__main__":
    main()
