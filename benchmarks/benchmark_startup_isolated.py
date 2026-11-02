"""Normal EXE startup benchmark, restricted to newly owned project build trees.

prepare never launches anything. measure requires --execute-authorized. No state
backup, release access, process termination, cache flushing, or package changes.
HTTP is off by default; WM_CLOSE then follows the seeded close-to-exit policy.
"""

import argparse
import configparser
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import statistics
import subprocess
import sys
import time
import urllib.request


REPO = Path(__file__).resolve().parents[1]
WORK = "startup-small-files-20261028-r1"
TMP_ROOT = REPO / "build/tmp" / WORK
AUDIT_ROOT = REPO / "build/audit" / WORK
OWNER = ".startup-benchmark.json"
STATE_NAMES = (".settings", ".pre_settings", "themes.json", "plugins/.plugins_state")
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def checked_path(path, boundary):
    path = Path(os.path.abspath(path))
    boundary = Path(os.path.abspath(boundary))
    require(path != boundary and path.is_relative_to(boundary), "Outside dedicated build boundary: " + str(path))
    for item in (path, *path.parents):
        require(not item.is_symlink() and not (hasattr(item, "is_junction") and item.is_junction()),
                "Links/junctions are not allowed: " + str(item))
    require(path.resolve() == path, "Resolved path differs: " + str(path))
    return path


def artifact_path(value):
    executable = checked_path(value, TMP_ROOT)
    require(executable.name == "Umi-OCR.exe" and executable.is_file(), "Expected an existing isolated Umi-OCR.exe")
    require((executable.parent / "UmiOCR-data/main.py").is_file(), "Missing normal launcher input")
    checked_path(executable.parent / "UmiOCR-data", TMP_ROOT)
    return executable


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def read_json(path):
    require(path.stat().st_size < 2 * 1024 * 1024, "Unexpectedly large benchmark metadata")
    return json.loads(path.read_text("utf-8"))


def _kernel():
    require(os.name == "nt", "Real startup measurement requires Windows")
    return ctypes.WinDLL("kernel32", use_last_error=True)


def running_in(root):
    kernel = _kernel()
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    pids = (wintypes.DWORD * 16384)()
    size = wintypes.DWORD()
    require(kernel.K32EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(size)), "Cannot enumerate running processes")
    require(size.value < ctypes.sizeof(pids), "Process enumeration exceeded bounded buffer")
    result = []
    for pid in pids[:size.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            continue  # Protected system processes are not operated on.
        try:
            buffer, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                if Path(buffer.value).is_relative_to(root):
                    result.append({"pid": int(pid), "executable": buffer.value})
        finally:
            kernel.CloseHandle(handle)
    return result


def assert_idle(root):
    occupants = running_in(root)
    require(not occupants, "Artifact is running; quit it normally first: " + json.dumps(occupants))


def listening_pids(port):
    class Row(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in ("state", "address", "port", "remote", "remotePort", "pid")]
    api = ctypes.WinDLL("iphlpapi", use_last_error=True).GetExtendedTcpTable
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                    wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
    api.restype = wintypes.ULONG
    size = wintypes.DWORD()
    for _ in range(3):
        buffer = ctypes.create_string_buffer(max(size.value, 4))
        result = api(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0)  # OWNER_PID_LISTENER
        if result == 122:
            continue
        require(result == 0, "Cannot verify TCP listener ownership")
        count = wintypes.DWORD.from_buffer_copy(buffer).value
        require(4 + count * ctypes.sizeof(Row) <= len(buffer), "Invalid TCP owner table")
        rows = [Row.from_buffer_copy(buffer, 4 + index * ctypes.sizeof(Row)) for index in range(count)]
        return {int(row.pid) for row in rows if socket.ntohs(row.port & 0xffff) == port}
    raise RuntimeError("TCP owner table changed beyond bounded retries")


STARTUP_ERROR_TITLE = "【错误】 Umi-OCR Error"
OK_LABELS = {"确定", "确定(&O)", "OK", "&OK"}


class _DialogWindows:
    """Read only, except an explicitly validated standard OK button click."""
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            "GetParent": ([wintypes.HWND], wintypes.HWND),
            "GetClassNameW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetWindowTextLengthW": ([wintypes.HWND], ctypes.c_int),
            "GetWindowTextW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            "GetDlgCtrlID": ([wintypes.HWND], ctypes.c_int),
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
            "IsWindowEnabled": ([wintypes.HWND], wintypes.BOOL),
            "EnumWindows": ([self.callback_type, wintypes.LPARAM], wintypes.BOOL),
            "EnumChildWindows": ([wintypes.HWND, self.callback_type, wintypes.LPARAM], wintypes.BOOL),
            "SendMessageTimeoutW": ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                      wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)], ctypes.c_ssize_t),
        }
        for name, (arguments, result) in signatures.items():
            method = getattr(self.user, name)
            method.argtypes, method.restype = arguments, result

    def windows(self, parent=None):
        found = []
        @self.callback_type
        def visit(hwnd, _unused):
            found.append(int(hwnd))
            return len(found) < (4096 if parent is None else 128)
        if parent is None:
            require(self.user.EnumWindows(visit, 0), "Cannot enumerate startup error windows")
        else:
            self.user.EnumChildWindows(parent, visit, 0)
        return found

    def pid(self, hwnd):
        owner = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        return owner.value

    def info(self, hwnd):
        kind = ctypes.create_unicode_buffer(128)
        self.user.GetClassNameW(hwnd, kind, len(kind))
        length = self.user.GetWindowTextLengthW(hwnd)
        text = ctypes.create_unicode_buffer(min(max(length + 1, 1), 32769))
        self.user.GetWindowTextW(hwnd, text, len(text))
        return {"hwnd": int(hwnd), "pid": self.pid(hwnd), "parent": int(self.user.GetParent(hwnd) or 0),
                "class": kind.value, "text": text.value, "textTruncated": length > 32768,
                "controlId": self.user.GetDlgCtrlID(hwnd), "visible": bool(self.user.IsWindowVisible(hwnd)),
                "enabled": bool(self.user.IsWindowEnabled(hwnd))}

    def click_ok(self, hwnd):
        result = ctypes.c_size_t()
        require(self.user.SendMessageTimeoutW(hwnd, 0xF5, 0, 0, 2, 2000, ctypes.byref(result)),
                "Validated OK button did not acknowledge BM_CLICK within 2000ms")


def find_owned_startup_error(pid, *, windows=None):
    windows = _DialogWindows() if windows is None else windows
    for hwnd in windows.windows():
        if windows.pid(hwnd) != pid:
            continue  # Do not even read the title/controls of another PID.
        dialog = windows.info(hwnd)
        if dialog["class"] != "#32770" or dialog["text"] != STARTUP_ERROR_TITLE or not dialog["visible"]:
            continue
        statics, buttons = [], []
        for child in windows.windows(hwnd):
            if windows.pid(child) != pid:
                continue
            info = windows.info(child)
            if info["parent"] != hwnd:
                continue
            if info["class"] == "Static":
                statics.append(info)
            elif info["class"] == "Button":
                buttons.append(info)
        return {"dialog": dialog, "statics": statics, "buttons": buttons,
                "staticTexts": [info["text"] for info in statics if info["text"]]}
    return None


def dismiss_owned_startup_error(pid, evidence, *, windows=None):
    windows = _DialogWindows() if windows is None else windows
    dialog = windows.info(evidence["dialog"]["hwnd"])
    require(dialog["pid"] == pid and dialog["class"] == "#32770" and dialog["text"] == STARTUP_ERROR_TITLE
            and dialog["visible"], "Startup error dialog identity changed; no click sent")
    require(len(evidence["buttons"]) == 1 and evidence["staticTexts"], "Not the captured standard single-OK error dialog")
    button = windows.info(evidence["buttons"][0]["hwnd"])
    require(button["pid"] == pid and button["parent"] == dialog["hwnd"] and button["class"] == "Button"
            and button["controlId"] == 1 and button["text"] in OK_LABELS and button["visible"] and button["enabled"],
            "Startup error OK button identity/parent/label changed; no click sent")
    windows.click_ok(button["hwnd"])
    return {"method": "BM_CLICK", "message": 0xF5, "flags": 2, "timeoutMs": 2000,
            "dialogHwnd": dialog["hwnd"], "buttonHwnd": button["hwnd"], "buttonLabel": button["text"]}


def own_window(pid):
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    @callback_type
    def visit(hwnd, _unused):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        text = ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(hwnd, text, len(text))
        kind = ctypes.create_unicode_buffer(128)
        user.GetClassNameW(hwnd, kind, len(kind))
        if (owner.value == pid and user.IsWindowVisible(hwnd) and text.value.startswith("Umi-OCR")
                and kind.value.startswith("Qt") and "QWindow" in kind.value):
            found.append(hwnd)
        return True
    user.EnumWindows(visit, 0)
    return found[0] if found else None


def window_message(pid, *, close=False):
    hwnd = own_window(pid)
    require(hwnd is not None, "No visible root window owned by benchmark PID")
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    owner = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    require(owner.value == pid, "Window ownership changed; no message was sent")
    if close:
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        require(user.PostMessageW(hwnd, 0x0010, 0, 0), "WM_CLOSE could not be queued")
    else:
        result = ctypes.c_size_t()
        user.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        require(user.SendMessageTimeoutW(hwnd, 0, 0, 0, 2, 1000, ctypes.byref(result)), "UI did not acknowledge WM_NULL")


def own_command(pid, port, arguments):
    require(listening_pids(port) == {pid}, "Refuse HTTP request: port is not owned exclusively by this sample PID")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(f"http://127.0.0.1:{port}/argv", data=json.dumps(arguments).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=2) as response:
        require(response.status == 200, "CLI route did not acknowledge request")
        return response.read(64 * 1024).decode("utf-8")


def prepare(args):
    executable = artifact_path(args.artifact)
    root, data = executable.parent, executable.parent / "UmiOCR-data"
    assert_idle(root)
    require(not (root / OWNER).exists(), "Artifact is already owned; never adopt an old run")
    for name in STATE_NAMES:
        path = checked_path(data / name, TMP_ROOT)
        require(not path.exists(), "Refuse existing portable/user state: " + str(path))
    require(RUN_ID.fullmatch(args.identity) is not None, "Invalid artifact identity")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    # Configs normalizes boolean/number/enum INI scalars. Missing page history
    # intentionally selects the real Navigation default, not a fake QML scene.
    settings = ("[Global]\nserver.enable=" + str(args.http).lower() + "\nserver.host=127.0.0.1\n"
        f"server.port={port}\nocr.lifecycle.warmupMode=lazy\nocr.lifecycle.cleanupPolicy=never\n"
        "window.startupInvisible=false\nwindow.closeWin2Hide=false\nwindow.simpleNotificationType=none\n"
        "ui.theme=Default Light\nui.scale=1\n")
    with (data / ".settings").open("x", encoding="utf-8") as stream:
        stream.write(settings)
    write_new(data / ".pre_settings", {"i18n": "zh_CN", "opengl": "", "server_port": port, "last_pid": -1, "last_ptime": -1})
    state_root = checked_path(root / ".startup-state", TMP_ROOT)
    state_root.mkdir()
    for name in ("temp", "cache", "roaming", "local", "shader"):
        (state_root / name).mkdir()
    owner = {"format": "umi-isolated-startup-v1", "artifact": str(executable), "identity": args.identity,
             "exeSha256": hashlib.sha256(executable.read_bytes()).hexdigest(), "http": args.http,
             "profile": "Navigation/zh_CN/Default Light/100%/visible/lazy/close-to-exit",
             "settingsSeedSha256": hashlib.sha256(settings.encode("utf-8")).hexdigest(), "createdNs": time.time_ns(),
             "limits": "Identity label is not source verification; use the formal build audit. No inference is requested."}
    write_new(root / OWNER, owner)
    return {"status": "PREPARED_NOT_RUN", **owner}


def verify_state(executable, owner):
    data = executable.parent / "UmiOCR-data"
    for name in STATE_NAMES:
        checked_path(data / name, TMP_ROOT)
    record = read_json(data / ".pre_settings")
    pid = record.get("last_pid", -1)
    require(isinstance(pid, int), "Invalid isolated instance PID record")
    if pid > 0:
        kernel = _kernel()
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            try:
                code = wintypes.DWORD()
                require(kernel.GetExitCodeProcess(handle, ctypes.byref(code)), "Cannot verify recorded instance PID")
                require(code.value != 259, "Instance record points to a live PID; refuse CLI forwarding: " + str(pid))
            finally:
                kernel.CloseHandle(handle)
        else:
            require(ctypes.get_last_error() == 87, "Cannot establish that the recorded instance PID has exited")
    config = configparser.ConfigParser(interpolation=None)
    config.read(checked_path(data / ".settings", TMP_ROOT), encoding="utf-8-sig")
    expected = {"server.enable": str(owner["http"]).lower(), "server.host": "127.0.0.1", "ocr.lifecycle.warmupMode": "lazy",
                "window.startupInvisible": "false", "window.closeWin2Hide": "false"}
    for key, value in expected.items():
        require(config.get("Global", key, fallback="").strip('"') == value, "Isolated configuration drift: " + key)


def load_owner(executable):
    root = executable.parent
    owner = read_json(checked_path(root / OWNER, TMP_ROOT))
    require(owner.get("format") == "umi-isolated-startup-v1" and owner.get("artifact") == str(executable), "Artifact owner mismatch")
    require(hashlib.sha256(executable.read_bytes()).hexdigest() == owner["exeSha256"], "EXE changed after preparation")
    verify_state(executable, owner)
    return owner


def collect_events(path, pid, run_id):
    if not path.exists():
        return []
    require(path.stat().st_size < 512 * 1024, "Trace exceeded bounded startup evidence size")
    lines = path.read_bytes().splitlines(keepends=True)
    events = [json.loads(line) for line in lines if line.endswith(b"\n")]
    require(all(event.get("format") == "umi-startup-trace-v1" and event.get("pid") == pid and event.get("runId") == run_id
                and event.get("clock") == "windows-perf-counter-ns" and isinstance(event.get("t_ns"), int)
                for event in events), "Trace format/PID/run-id/clock mismatch")
    stages = [event for event in events if event["event"] in {"S0", "S1", "S2", "S3", "S4", "S5", "S6"}]
    require([event["event"] for event in stages] == ["S" + str(index) for index in range(len(stages))], "Missing/duplicate/out-of-order startup stages")
    require(all(left["t_ns"] <= right["t_ns"] for left, right in zip(stages, stages[1:])), "Startup clocks are not aligned")
    return events


def sample(executable, owner, output, index, timeout, dwell, exit_timeout):
    run_id = output.name + "-" + str(index)
    require(RUN_ID.fullmatch(run_id) is not None, "Output name is too long for a startup run ID")
    trace_path = output / (run_id + ".jsonl")
    env = os.environ.copy()
    state = executable.parent / ".startup-state"
    for key, name in (("TEMP", "temp"), ("TMP", "temp"), ("XDG_CACHE_HOME", "cache"),
                      ("APPDATA", "roaming"), ("LOCALAPPDATA", "local"), ("QT_SHADER_CACHE_PATH", "shader")):
        env[key] = str(checked_path(state / name, TMP_ROOT))
    env.update(UMI_STARTUP_TRACE=str(trace_path), UMI_STARTUP_RUN_ID=run_id)
    result = {"runId": run_id, "trace": str(trace_path), "status": "FAIL", "normalExit": False}
    process, events, ready_ns, port = None, [], None, None
    try:
        assert_idle(executable.parent)
        verify_state(executable, owner)
        # No hashes, builds, state reset, or package scans inside the timed path.
        s0 = time.perf_counter_ns()
        env["UMI_STARTUP_S0_NS"] = str(s0)
        process = subprocess.Popen([str(executable)], cwd=executable.parent, env=env, close_fds=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        result.update(pid=process.pid, s0_ns=s0)
        deadline = time.perf_counter() + timeout
        next_dialog_scan = 0.0
        while time.perf_counter() < deadline:
            require(process.poll() is None, "Program exited before startup observation completed")
            if time.perf_counter() >= next_dialog_scan:
                next_dialog_scan = time.perf_counter() + 0.1
                dialog = find_owned_startup_error(process.pid)
                if dialog is not None:
                    result["startupErrorDialog"] = dialog
                    raise RuntimeError("Owned standard Umi-OCR startup error: " + "\n".join(dialog["staticTexts"]))
            events = collect_events(trace_path, process.pid, run_id)
            stages = {event["event"]: event for event in events if event["event"] in {"S0", "S1", "S2", "S3", "S4", "S5", "S6"}}
            errors = [event for event in events if event["event"] == "observer-error"]
            require(not errors, "In-process observer failed: " + json.dumps(errors))
            if "S5" in stages and ready_ns is None:
                snapshot = stages["S5"]["details"]["state"]
                require(snapshot["pageKey"] == "Navigation" and snapshot["httpEnabled"] is owner["http"], "Unexpected startup page/HTTP profile")
                port = int(snapshot["httpPort"])
                if owner["http"]:
                    response = own_command(process.pid, port, ["--all_pages"])
                    require("All opened pages:" in response and "Navigation" in response, "Real CLI page response is not ready")
                else:
                    window_message(process.pid)
                ready_ns = time.perf_counter_ns()
                result["readinessAck"] = "owned-loopback-CLI" if owner["http"] else "owned-window-WM_NULL"
            if "S6" in stages and ready_ns is not None and (time.perf_counter_ns() - ready_ns) / 1e9 >= dwell:
                result.update(status="PASS", stagesMs={key: event["sinceS0Ms"] for key, event in stages.items()},
                              interactiveMs=max(stages["S5"]["sinceS0Ms"], (ready_ns - s0) / 1e6))
                break
            time.sleep(0.01)
        else:
            raise TimeoutError("Startup stages/real readiness did not finish before the finite timeout")
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    dialog = result.get("startupErrorDialog") or find_owned_startup_error(process.pid)
                    if dialog is not None:
                        result["status"] = "FAIL"
                        result["startupErrorDialog"] = dialog
                        result.setdefault("error", "Owned standard Umi-OCR startup error: " + "\n".join(dialog["staticTexts"]))
                        result["errorDialogAcknowledgement"] = dismiss_owned_startup_error(process.pid, dialog)
                        result["exitRequest"] = "Validated startup-error OK button BM_CLICK"
                    else:
                        if owner["http"] and port is not None:
                            own_command(process.pid, port, ["--quit"])
                        else:
                            window_message(process.pid, close=True)
                        result["exitRequest"] = "CLI --quit" if owner["http"] and port is not None else "WM_CLOSE (close-to-exit)"
                except Exception as exc:
                    result["exitRequestError"] = str(exc)
                try:
                    process.wait(timeout=exit_timeout)
                except subprocess.TimeoutExpired:
                    result["status"] = "FAIL"
                    result["leftRunningPid"] = process.pid
                    result["exitError"] = "Normal exit timed out; no process was terminated. Quit this isolated instance normally."
            result["returncode"] = process.poll()
            result["normalExit"] = process.poll() == 0
            if not result["normalExit"]:
                result["status"] = "FAIL"
            else:
                try:
                    result["remainingArtifactProcesses"] = running_in(executable.parent)
                    if result["remainingArtifactProcesses"]:
                        result["status"] = "FAIL"  # Retain evidence; never stop these processes.
                except Exception as exc:
                    result["processCheckError"], result["status"] = str(exc), "FAIL"
            try:
                events = collect_events(trace_path, process.pid, run_id)
                result["shutdownObserved"] = any(event["event"] == "qt-exec-returned" for event in events)
                result["heartbeat"] = next((event["details"] for event in reversed(events) if event["event"] == "qt-about-to-quit"), None)
                if not result["shutdownObserved"]:
                    result["status"] = "FAIL"
            except Exception as exc:
                result["evidenceError"], result["status"] = str(exc), "FAIL"
    return result


def measure(args):
    require(args.execute_authorized, "Real GUI measurement needs explicit --execute-authorized")
    require(os.name == "nt" and sys.version_info >= (3, 10), "Use Windows Python 3.10+ for the shared cross-process perf counter")
    require(0 <= args.warmups <= 10 and 1 <= args.samples <= 30, "Invalid bounded sample counts")
    require(1 <= args.timeout <= 300 and 1 <= args.exit_timeout <= 120 and 0 <= args.dwell <= 10, "Invalid finite time budget")
    executable = artifact_path(args.artifact)
    output = checked_path(args.output, AUDIT_ROOT)
    require(RUN_ID.fullmatch(output.name + "-40") is not None, "Invalid output/run name")
    require(not output.exists(), "Use a new evidence directory")
    owner = load_owner(executable)  # All identity hashes finish before timing.
    assert_idle(executable.parent)
    output.mkdir(parents=True)
    report = {"format": "umi-isolated-startup-results-v1", "owner": owner, "artifact": str(executable),
              "clock": "windows-perf-counter-ns", "warmups": args.warmups, "samples": [], "status": "FAIL",
              "conditions": "Same package layout required; isolated persistent Qt caches/state; no OS cache flush. First run is not claimed cold.",
              "modelInference": "NOT_REQUESTED", "cliForwarding": "measured" if owner["http"] else "NOT_TESTED_HTTP_DISABLED"}
    write_new(output / "inputs.json", {"owner": owner, "arguments": vars(args), "python": sys.version,
        "benchmarkPath": str(Path(__file__).resolve()), "benchmarkSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "clockInfo": vars(time.get_clock_info("perf_counter")), "environment": {key: os.environ.get(key) for key in
        ("QML_DISABLE_DISK_CACHE", "QML_DISK_CACHE_PATH", "CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER")}})
    for index in range(args.warmups + args.samples):
        result = sample(executable, owner, output, index, args.timeout, args.dwell, args.exit_timeout)
        result["warmup"] = index < args.warmups  # UI repetition only, never model prewarming.
        report["samples"].append(result)
        write_new(output / f"sample-{index}.json", result)
        if result["status"] != "PASS":
            break
    values = [entry["interactiveMs"] for entry in report["samples"] if not entry["warmup"] and entry["status"] == "PASS"]
    if len(values) == args.samples:
        report.update(status="PASS", medianInteractiveMs=statistics.median(values), minInteractiveMs=min(values), maxInteractiveMs=max(values),
                      stdevInteractiveMs=statistics.stdev(values) if len(values) > 1 else None)
    write_new(output / "report.json", report)
    return {"status": report["status"], "report": str(output / "report.json"), "samples": len(report["samples"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("self-check", help="Print the parameter/safety contract without launching or preparing an artifact")
    prep = commands.add_parser("prepare", help="Create only new isolated settings; never launches the program")
    prep.add_argument("--artifact", required=True)
    prep.add_argument("--identity", required=True)
    prep.add_argument("--http", action="store_true", help="Explicit identical loopback/CLI profile for both comparison arms")
    run = commands.add_parser("measure")
    run.add_argument("--artifact", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--execute-authorized", action="store_true")
    run.add_argument("--warmups", type=int, default=1)
    run.add_argument("--samples", type=int, default=5)
    run.add_argument("--timeout", type=float, default=30)
    run.add_argument("--exit-timeout", type=float, default=40)
    run.add_argument("--dwell", type=float, default=0.5)
    args = parser.parse_args(argv)
    if args.command == "self-check":
        result = {"status": "PARAMETERS_OK_NOT_RUN", "tmpBoundary": str(TMP_ROOT), "auditBoundary": str(AUDIT_ROOT),
                  "defaultHttp": False, "defaultExit": "PID-owned WM_CLOSE; close-to-exit only", "launchRequires": "--execute-authorized",
                  "s6Scope": "Named startup callbacks/native title/CUDA discovery/plugin operations; lazy warmup only", "guiStarted": False}
    else:
        result = prepare(args) if args.command == "prepare" else measure(args)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
