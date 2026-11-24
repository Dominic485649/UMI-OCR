"""真实包内EXE、Shell托盘、第二实例CLI与正常退出；不截图、不推理。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build/tools"))
import runtime_archive_layout as layout
import merge_runtime as merge
from staging_smoke import configure_runtime

_spec = importlib.util.spec_from_file_location("native_shell_helpers", ROOT / "tests/test_windows_tray.py")
shell = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shell)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    require(os.name == "nt", "只验证实际Windows Shell")
    root, output, log = map(layout.plain_path, (args.root, args.output, args.log))
    root.relative_to(ROOT / "build/tmp")
    output.relative_to(ROOT / "build/audit")
    log.relative_to(ROOT / "build/audit")
    require(not output.exists() and not log.exists() and output.parent.is_dir() and log.parent.is_dir(), "报告/日志必须全新")
    executable = root / "Umi-OCR.exe"
    require(executable.is_file() and not merge.running_processes(root), "测试程序缺失或已被占用，不改写配置或终止进程")
    data = root / "UmiOCR-data"
    version = layout.read_json(data / "about.json")["version"]
    expected_version = ".".join(str(version[name]) for name in ("major", "minor", "patch"))
    saved = {data / name: ((data / name).read_bytes() if (data / name).exists() else None) for name in (".settings", ".pre_settings")}
    handles = configure_runtime(data)
    from PySide6.QtCore import QSettings
    settings = QSettings(str(data / ".settings"), QSettings.Format.IniFormat)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    for name, value in {"server.enable": True, "server.host": "127.0.0.1", "server.port": port,
                        "window.startupInvisible": True, "ocr.lifecycle.warmupMode": "lazy"}.items():
        settings.setValue("Global/" + name, value)
    settings.sync()
    settings = None
    pre = json.loads(saved[data / ".pre_settings"].decode("utf-8-sig")) if saved[data / ".pre_settings"] else {}
    pre.update(last_pid=-1, last_ptime=-1, server_port=port)
    (data / ".pre_settings").write_text(json.dumps(pre), encoding="utf-8")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base_url = f"http://127.0.0.1:{port}"
    process = None
    report = {"status": "FAIL", "root": str(root), "exe_sha256": layout.sha256_file(executable),
              "desktopCapture": "NOT_RUN", "modelInference": "NOT_RUN", "userConfigurationTouched": False,
              "test_sources": {name: layout.sha256_file(ROOT / name) for name in ("tests/test_release312_native.py", "tests/test_windows_tray.py")}}

    def quit_normally():
        request = urllib.request.Request(base_url + "/argv", data=b'["--quit"]', headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=10) as response:
            return response.read(4096).decode("utf-8")

    try:
        with log.open("xb") as stream:
            process = subprocess.Popen([str(executable), "--force"], cwd=root, stdin=subprocess.DEVNULL,
                                       stdout=stream, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            deadline, icons = time.monotonic() + 45, []
            while not icons:
                require(process.poll() is None, "真实EXE在托盘注册前退出")
                require(time.monotonic() < deadline, "Shell托盘注册超时")
                icons = shell.shell_icons(process.pid)
                if not icons:
                    time.sleep(.05)
            readiness = shell.wait_http_ready(opener, base_url, process, expected_version)
            client = subprocess.run([str(executable), "--hide"], cwd=root, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=25,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            reply = client.stdout.decode("utf-8", errors="replace")
            require(client.returncode == 0 and "Umi-OCR hide." in reply and process.poll() is None, "第二实例CLI未转发给同一实际EXE")
            quit_reply = quit_normally()
            process.wait(timeout=25)
            require(process.returncode == 0 and "Umi-OCR quit." in quit_reply, "程序未通过正常退出路径")
            report.update(status="PASS", pid=process.pid, shell_icons=icons, http_ready_before_quit=readiness["ready"],
                          http_readiness=readiness, cli_forwarded=True, cli_reply=reply,
                          quit_reply=quit_reply, exit_code=process.returncode)
    except BaseException:
        report["error"] = traceback.format_exc()
    finally:
        if process and process.poll() is None:
            try:
                report["cleanupQuitReply"] = quit_normally()
                process.wait(timeout=15)
            except Exception as error:
                report["cleanupError"] = "正常退出未成功，保留测试配置，不终止进程：" + str(error)
        if not process or process.poll() is not None:
            require(not merge.running_processes(root), "仍有测试目录进程，停止恢复设置，不终止进程")
            for path, original in saved.items():
                if original is None:
                    if path.exists():
                        layout.plain_path(path).unlink()
                else:
                    layout.plain_path(path).write_bytes(original)
            report["ownedTestSettingsRestored"] = True
        else:
            report.update(status="FAIL", processStillRunning=process.pid, ownedTestSettingsRestored=False)
        report["log"] = {"path": str(log), "sha256": layout.sha256_file(log)} if log.exists() else None
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
