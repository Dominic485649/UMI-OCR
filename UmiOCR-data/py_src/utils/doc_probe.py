"""在短生命周期的独立 Python 进程中读取文档信息，不共享主程序的 MuPDF 上下文。"""

import itertools
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from threading import Thread


PROBE_BATCH_SIZE = 16
_MAX_REQUEST_BYTES = 2 * 1024 * 1024
_MAX_OUTPUT_BYTES = PROBE_BATCH_SIZE * 8192

# 只挂载可信应用代码和便携依赖。文档路径、密码只从 stdin 传入，不能出现在命令行。
# run_module 可直接读取 app.zip 中的 helper，无须向文档目录或临时数据目录解压代码。
_WORKER_BOOTSTRAP = """
import os
import runpy
import sys
code_root, runtime_root = sys.argv[1:]
sys.path[:0] = [
    code_root,
    os.path.join(runtime_root, 'site-packages'),
    os.path.join(runtime_root, 'dependencies.zip'),
]
runpy.run_module('py_src.utils._doc_probe_worker', run_name='__main__')
"""


def _failure(path, message, kind="unreadable"):
    return {
        "path": path,
        "page_count": 0,
        "is_encrypted": False,
        "is_authenticate": False,
        "error": message,
        "error_kind": kind,
    }


def _runtime_paths():
    # 保留逻辑路径，与插件 worker 一致，不把 staging 的目录联接解析到别处。
    code_root = Path(os.path.abspath(__file__)).parents[2]
    app_root = code_root.parent if code_root.suffix.lower() == ".zip" else code_root
    bundled_python = app_root / "runtime" / ("python.exe" if os.name == "nt" else "python")
    worker_python = Path(sys.executable)
    if bundled_python.is_file():
        worker_python = bundled_python
    elif not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?w?(?:\.exe)?", worker_python.name, re.I):
        # 原生嵌入时 sys.executable 是 Umi-OCR.exe，绝不能误启动另一个 GUI 实例。
        raise RuntimeError("找不到应用的便携 Python，无法安全读取文档。")
    if not worker_python.is_file():
        raise RuntimeError("文档读取所需的 Python 解释器不存在。")
    runtime_root = app_root
    if not (runtime_root / "site-packages").is_dir() and worker_python.parent.name.lower() == "runtime":
        # 源码回归只借用当前便携解释器的依赖，不退回旧 app.zip 的应用代码。
        runtime_root = worker_python.parent.parent
    return code_root, app_root, runtime_root, worker_python


def _read_records(stream, count):
    stream.seek(0)
    raw = stream.read(_MAX_OUTPUT_BYTES + 1)
    if len(raw) > _MAX_OUTPUT_BYTES:
        return [], "文档读取子进程的响应过大。"
    records = []
    try:
        for line in raw.splitlines():
            record = json.loads(line)
            if not isinstance(record, dict) or record.get("index") != len(records) or len(records) >= count:
                raise ValueError("响应顺序无效")
            info = record["info"]
            if not isinstance(info, dict):
                raise ValueError("文档信息类型无效")
            if type(info.get("page_count")) is not int or info["page_count"] < 0:
                raise ValueError("页数无效")
            if type(info.get("is_encrypted")) is not bool or type(info.get("is_authenticate")) is not bool:
                raise ValueError("密码状态无效")
            clean = {key: info[key] for key in ("page_count", "is_encrypted", "is_authenticate")}
            if "error" in info:
                if not isinstance(info["error"], str) or not info["error"] or len(info["error"]) > 1024:
                    raise ValueError("错误信息无效")
                clean["error"] = info["error"]
                clean["error_kind"] = "workererror" if info.get("error_kind") == "workererror" else "unreadable"
            records.append(clean)
    except (KeyError, TypeError, ValueError, UnicodeError):
        return records, "文档读取子进程返回了无效数据。"
    return records, ""


def _run_batch(requests, password, timeout):
    code_root, app_root, runtime_root, worker_python = _runtime_paths()
    payload = json.dumps({"documents": requests, "password": password}, ensure_ascii=False).encode("utf-8")
    if len(payload) > _MAX_REQUEST_BYTES:
        raise ValueError("文档读取请求过大，请减少单次导入数量或密码长度。")
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    # 不继承 PyMuPDF 的输出重定向设置，避免将解析诊断写入其它文件。
    environment.pop("PYMUPDF_MESSAGE", None)
    environment.pop("PYMUPDF_LOG", None)
    timed_out = False
    # 输出有固定上限；解析器的原生诊断不进入管道，也不保留含用户信息的日志。
    # 临时文件只存协议响应，且必须先终止并回收自己创建的进程，再关闭/清理。
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            [str(worker_python), "-I", "-X", "utf8", "-u", "-c", _WORKER_BOOTSTRAP, str(code_root), str(runtime_root)],
            cwd=str(app_root),
            env=environment,
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        def send_input():
            try:
                with process.stdin as stream:
                    stream.write(payload)
            except (OSError, ValueError):
                # 子进程提前退出或被超时终止时，写端允许收到断管。
                pass

        # Windows 的 communicate 会先同步写 stdin，大请求遇到不读输入的
        # 子进程可能卡在管道写入，根本走不到 timeout。只把写入放到私有线程，
        # 调用线程负责整个子进程的期限；回收进程后必须同时回收这个写线程。
        writer = Thread(target=send_input, name="UmiOCR-DocProbe-stdin", daemon=True)
        try:
            writer.start()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            if writer.ident is not None:
                writer.join()
            if not process.stdin.closed:
                process.stdin.close()
        records, protocol_error = _read_records(output, len(requests))
    if protocol_error:
        return records, "workererror", protocol_error
    if timed_out:
        return records, "timeout", f"文档读取超时（{timeout:g} 秒）。"
    if process.returncode:
        return records, "workererror", f"文档读取子进程异常退出（代码 {process.returncode}）。"
    if len(records) != len(requests):
        return records, "workererror", "文档读取子进程未返回完整结果。"
    return records, "", ""


def _probe_batch(requests, password, timeout):
    results = []
    remaining = requests
    while remaining:
        try:
            records, kind, message = _run_batch(remaining, password, timeout)
        except Exception as exc:
            # 不包含请求或原始子进程输出，尤其不能把密码写入界面/日志。
            message = f"无法启动或通信文档读取子进程（{type(exc).__name__}）。"
            return results + [_failure(item["path"], message, "workererror") for item in remaining]
        if kind and len(records) == len(remaining):
            # 完整输出后仍可能在退出时崩溃或挂起，不能将异常静默当作全部成功。
            # 保留前面的结果，将最后一个文件的本次探测标为可见失败。
            records = records[:-1]
        for request, info in zip(remaining, records):
            results.append({"path": request["path"], **info})
        remaining = remaining[len(records):]
        if remaining:
            # 崩溃/超时时保留已完成的前缀，只将当前文件记为失败。
            # 后续文件换一个隔离进程继续，坏文档不能吞掉同一批的正常文档。
            results.append(_failure(remaining[0]["path"], message, kind))
            remaining = remaining[1:]
    return results


def probe_documents(paths, password="", timeout=30):
    """按有界小批次依次返回文档信息；每个子进程最多存活 timeout 秒。

    不读取页面内容，不创建常驻服务。单个子进程异常时继续探测剩余文件。
    无密码/错误密码不是读取异常，而是尚未通过验证的加密文档。
    """
    try:
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout <= 0 or not isinstance(password, str):
            raise ValueError("参数无效")
        parameter_error = ""
    except (TypeError, ValueError, OverflowError):
        parameter_error = "文档读取参数无效：密码必须是文本，超时必须是正有限秒数。"
    iterator = iter(paths)
    while True:
        batch = list(itertools.islice(iterator, PROBE_BATCH_SIZE))
        if not batch:
            return
        requests = []
        for path in batch:
            try:
                path = os.fsdecode(os.fspath(path))
                if not path or "\x00" in path:
                    raise ValueError("文档路径为空或包含空字符")
                request = {"path": path, "absolute_path": os.path.abspath(path)}
            except (TypeError, ValueError, OSError):
                if requests:
                    yield from _probe_batch(requests, password, timeout)
                    requests = []
                yield _failure(str(path), "文档路径无效。")
                continue
            if parameter_error:
                yield _failure(path, parameter_error)
            else:
                requests.append(request)
        if requests:
            yield from _probe_batch(requests, password, timeout)


def probe_document(path, password="", timeout=30):
    """返回兼容既有文档信息的 dict，失败附 error；本函数应在工作线程调用。

    is_encrypted 保存原始 needs_pass，不因成功验证而变成 False。
    is_authenticate 表示无需密码，或所给密码已通过验证。
    """
    return next(probe_documents([path], password=password, timeout=timeout))
