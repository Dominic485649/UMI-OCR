"""在隔离进程发现应用可见的 NVIDIA 逻辑设备，不启动推理服务。"""

from concurrent.futures import Future
from copy import deepcopy
import json
import os
import re
import subprocess
from threading import Event, Lock, Thread
import time

from .doc_probe import _runtime_paths
from .runtime_i18n import tr


_MAX_DEVICES = 64
_MAX_OUTPUT_BYTES = 64 * 1024
_MAX_NAME_BYTES = 255
_PROBE_TIMEOUT_SECONDS = 10.0
_CACHE_TTL_SECONDS = 30.0
_UUID_PATTERN = re.compile(r"GPU-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)

# 仅挂载应用源码或 app.zip；worker 只需要标准库，不挂载插件或推理依赖。
_WORKER_BOOTSTRAP = """
import runpy
import sys
code_root = sys.argv[1]
sys.path.insert(0, code_root)
runpy.run_module('py_src.utils._cuda_device_probe_worker', run_name='__main__')
"""

_MESSAGES = {
    "ready": "已发现 {count} 个 NVIDIA 设备。",
    "no_devices": "未发现可用的 NVIDIA 设备。",
    "driver_missing": "未找到 NVIDIA 驱动，请安装驱动后刷新。",
    "timeout": "NVIDIA 设备发现超时，请重试。",
    "failed": "NVIDIA 设备发现失败，请重试。",
}
_CACHE_LOCK = Lock()
_CACHE = {}
_INFLIGHT = {}


def _failure(state="failed", template=None):
    record = {"state": state, "devices": []}
    if template:
        record["message_template"] = template
    return record


def _present(record):
    # 缓存机器数据而非译文，语言热切换后仍使用当前语言的稳定模板。
    devices = deepcopy(record["devices"])
    state = record["state"]
    return {
        "ok": state in {"ready", "no_devices"},
        "state": state,
        "devices": devices,
        "message": tr(record.get("message_template", _MESSAGES[state]), count=len(devices)),
    }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("响应字段重复")
        result[key] = value
    return result


def _parse_output(raw):
    """将子进程响应视为不可信数据；不保留额外字段或原始错误。"""
    if len(raw) > _MAX_OUTPUT_BYTES:
        return _failure(template="NVIDIA 设备发现响应过大。")
    try:
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        if type(record) is not dict or set(record) != {"state", "devices"}:
            raise ValueError("响应字段无效")
        state, devices = record["state"], record["devices"]
        if type(state) is not str or state not in {"ready", "no_devices", "driver_missing", "failed"}:
            raise ValueError("响应状态无效")
        if type(devices) is not list or len(devices) > _MAX_DEVICES:
            raise ValueError("设备列表无效")
        if (state == "ready") != bool(devices):
            raise ValueError("响应状态与设备数量不符")
        uuids = set()
        for ordinal, device in enumerate(devices):
            if type(device) is not dict or set(device) != {"value", "ordinal", "name", "uuid"}:
                raise ValueError("设备字段无效")
            if type(device["ordinal"]) is not int or device["ordinal"] != ordinal:
                raise ValueError("逻辑序号不连续或重复")
            if type(device["value"]) is not str or device["value"] != f"gpu:{ordinal}":
                raise ValueError("逻辑设备值无效")
            name, uuid = device["name"], device["uuid"]
            if (type(name) is not str or not name.strip() or len(name) > _MAX_NAME_BYTES
                    or len(name.encode("utf-8")) > _MAX_NAME_BYTES
                    or any(ord(char) < 32 or 127 <= ord(char) < 160 for char in name)):
                raise ValueError("设备名称无效")
            if type(uuid) is not str or not _UUID_PATTERN.fullmatch(uuid) or uuid.casefold() in uuids:
                raise ValueError("设备 UUID 无效或重复")
            uuids.add(uuid.casefold())
        return record
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        return _failure(template="NVIDIA 设备发现返回了无效数据。")


def _run_probe(paths, environment):
    code_root, app_root, _runtime_root, worker_python = paths
    deadline = time.monotonic() + _PROBE_TIMEOUT_SECONDS
    process = subprocess.Popen(
        [str(worker_python), "-I", "-B", "-X", "utf8", "-u", "-c", _WORKER_BOOTSTRAP, str(code_root)],
        cwd=str(app_root),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    finished = Event()
    response = []
    read_failed = []

    def read_response():
        try:
            # 最多读取上限加一字节；不使用会无限累积输出的 communicate。
            response.append(process.stdout.read(_MAX_OUTPUT_BYTES + 1))
        except (OSError, ValueError):
            read_failed.append(True)
        finally:
            finished.set()

    reader = None
    timed_out = False
    try:
        reader = Thread(target=read_response, name="UmiOCR-CudaDeviceProbe-stdout", daemon=True)
        reader.start()
        if not finished.wait(max(0.0, deadline - time.monotonic())):
            timed_out = True
        elif not read_failed and len(response[0]) <= _MAX_OUTPUT_BYTES:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        # 只操作本次 Popen 返回的进程句柄；先回收它，再关闭管道及读线程。
        if process.poll() is None:
            process.kill()
        process.wait()
        if reader is not None and reader.ident is not None:
            reader.join()
        process.stdout.close()
    if response and len(response[0]) > _MAX_OUTPUT_BYTES:
        return _failure(template="NVIDIA 设备发现响应过大。")
    if timed_out:
        return _failure("timeout")
    if read_failed:
        return _failure()
    if process.returncode:
        return _failure(template="NVIDIA 设备发现子进程异常退出。")
    return _parse_output(response[0])


def _cache_key(paths, environment):
    return (
        *(os.path.normcase(os.path.abspath(path)) for path in paths),
        environment.get("CUDA_VISIBLE_DEVICES"),
        environment.get("CUDA_DEVICE_ORDER"),
    )


def discover_cuda_devices(force=False):
    """在线程中调用；同一环境的并发发现合并，缓存机器数据 30 秒。

    force 跳过已完成缓存，但仍加入同键的在途发现；不重排驱动逻辑序号。
    运行时解析及通信失败只返回本地化状态，不暴露目录或子进程原始输出。
    """
    try:
        paths = _runtime_paths()
        if not all(os.path.isabs(path) for path in paths):
            raise ValueError("运行路径必须为绝对路径")
        environment = os.environ.copy()
        key = _cache_key(paths, environment)
    except Exception:
        return _present(_failure(template="无法安全启动 NVIDIA 设备发现。"))
    with _CACHE_LOCK:
        now = time.monotonic()
        # 环境或运行时改变后可使用独立缓存，过期项不长期留存。
        for old_key, (expires, _) in list(_CACHE.items()):
            if expires <= now:
                del _CACHE[old_key]
        future = _INFLIGHT.get(key)
        cached = _CACHE.get(key)
        if future is None and not force and cached is not None:
            record = cached[1]
            leader = False
        else:
            record = None
            leader = future is None
            if leader:
                future = Future()
                _INFLIGHT[key] = future
    if record is not None:
        return _present(record)
    if leader:
        record = _failure()
        try:
            record = _run_probe(paths, environment)
        except Exception:
            # 不把异常文本（可能包含安装目录或环境信息）传给界面。
            pass
        finally:
            with _CACHE_LOCK:
                _CACHE[key] = (time.monotonic() + _CACHE_TTL_SECONDS, record)
                del _INFLIGHT[key]
                future.set_result(record)
    else:
        record = future.result()
    return _present(record)
