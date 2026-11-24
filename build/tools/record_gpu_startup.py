"""记录实际 CUDA worker 的初始化与正常退出，不执行 OCR 或授权发布。"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ID = "win32_PaddleOCRv6_CUDA"
LAUNCHER_NAME = "UmiOCR-CudaWorker.exe"
MODEL_NAMES = [
    "PP-LCNet_x1_0_doc_ori", "UVDoc", "PP-LCNet_x1_0_textline_ori",
    "PP-OCRv6_medium_det", "PP-OCRv6_medium_rec",
]
PROPRIETARY_MODULES = {"paddle", "paddleocr", "paddlex", "cv2", "onnxruntime"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def plain(path: Path) -> Path:
    if str(path).startswith(("\\\\", "//", "\\/", "/\\")) or ".." in path.parts:
        raise ValueError("启动记录路径不能使用网络路径或上级目录段")
    value = path.absolute()
    if not value.is_relative_to(ROOT):
        raise ValueError("启动记录输入输出必须在本项目内")
    for node in (value, *value.parents):
        if node.is_symlink() or node.is_junction():
            raise ValueError("启动记录路径不能经过链接或 junction")
    return value


def file_hashes(root: Path, *, adapter: bool = False) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*.py") if adapter else root.rglob("*")):
        relative = path.relative_to(root)
        if adapter and {"vendor", "models", "__pycache__"} & set(relative.parts):
            continue
        plain(path)
        if path.is_file():
            result[relative.as_posix()] = digest(path)
    if not result:
        raise ValueError("启动记录所需的源码或模型集合为空")
    return result


def tree_binding(files: dict[str, str]) -> dict:
    checksum = hashlib.sha256()
    for name, value in sorted(files.items()):
        checksum.update(name.encode("utf-8") + b"\0" + value.encode("ascii") + b"\n")
    return {"files": len(files), "sha256": checksum.hexdigest()}


def validate_startup(startup, pid: int, data: Path, device: str) -> None:
    if not isinstance(startup, dict):
        raise ValueError("实际 worker 未返回启动信息")
    if type(startup.get("pid")) is not int or startup["pid"] != pid:
        raise ValueError("启动记录不是当前 worker 进程")
    if type(startup.get("native_code_page")) is not int or startup["native_code_page"] != 65001:
        raise ValueError("实际 worker 的原生代码页不是 UTF-8")
    if startup.get("python_utf8_mode") is not True:
        raise ValueError("实际 worker 未开启 Python UTF-8 模式")
    for key in ("stdin_encoding", "stdout_encoding"):
        if startup.get(key) != "utf-8":
            raise ValueError("实际 worker 的标准流不是 UTF-8")
    dll = startup.get("python_dll")
    expected_dll = data / "runtime/python313.dll"
    if not isinstance(dll, str) or Path(dll).absolute() != expected_dll.absolute():
        raise ValueError("实际 worker 未加载候选本体的 Python DLL")
    if startup.get("model_names") != MODEL_NAMES or startup.get("device") != device:
        raise ValueError("实际 worker 未初始化预期 CUDA 设备及五个模型")
    if not isinstance(startup.get("python_version"), str) or not startup["python_version"].startswith("3.13."):
        raise ValueError("实际 worker 的 Python 版本不符")


def record(staging: Path, output: Path, log_path: Path, expected_parent_acp: int, device: str) -> dict:
    if os.name != "nt" or not re.fullmatch(r"gpu:[0-9]+", device):
        raise ValueError("启动记录仅支持 Windows CUDA 设备")
    staging, output, log_path = (plain(path) for path in (staging, output, log_path))
    audit = ROOT / "build/audit"
    if not output.is_relative_to(audit) or not log_path.is_relative_to(audit):
        raise ValueError("启动证据和日志必须在 build/audit 内")
    if staging == output or staging in output.parents or staging == log_path or staging in log_path.parents:
        raise ValueError("启动证据不能写入候选程序")
    if output == log_path or output.exists() or log_path.exists():
        raise ValueError("启动证据和日志必须全新且不同，不覆盖旧记录")
    if not output.parent.is_dir() or not log_path.parent.is_dir():
        raise ValueError("启动证据和日志的父目录须已存在")
    parent_acp = int(ctypes.windll.kernel32.GetACP())
    if parent_acp != expected_parent_acp:
        raise ValueError("父进程实际代码页不符，不能作为该组启动证明")
    data = staging / "UmiOCR-data"
    plugin = data / "plugins" / PLUGIN_ID
    launcher = plugin / LAUNCHER_NAME
    lock = plugin / "runtime.lock.json"
    required = (data / "about.json", launcher, plugin / "worker.py", plugin / "umi-plugin.json", lock, data / "runtime/python313.dll")
    for path in required:
        plain(path)
        if not path.is_file():
            raise ValueError("候选缺少本体信息、原生入口、worker 或运行时记录")
    manifest = json.loads((plugin / "umi-plugin.json").read_text("utf-8-sig"))
    about = json.loads((data / "about.json").read_text("utf-8-sig"))
    if manifest.get("id") != PLUGIN_ID:
        raise ValueError("启动记录的插件身份不符")
    sources = file_hashes(plugin, adapter=True)
    models = file_hashes(plugin / "models")
    launcher_hash, lock_hash = digest(launcher), digest(lock)
    environment_before = {key: os.environ.get(key) for key in ("TEMP", "TMP")}
    temporary_before = tempfile.tempdir
    temporary = Path(tempfile.mkdtemp(prefix="cuda-startup-", dir=log_path.parent))
    result = {
        "test_type": "real_gpu_worker_startup_only", "status": "FAIL",
        "scope": "GPU_STARTUP_ONLY_NOT_OCR_OR_RELEASE_AUTHORIZATION",
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "plugin_version": manifest.get("version"), "host_version": about.get("version"),
        "installation": str(staging), "installation_contains_non_ascii": not str(staging).isascii(),
        "parent_native_code_page": parent_acp, "device": device,
        "plugin_source_sha256": sources, "plugin_runtime_lock_sha256": lock_hash,
        "launcher": {"file": LAUNCHER_NAME, "sha256": launcher_hash},
        "models": tree_binding(models), "recording_tool_sha256": digest(Path(__file__)),
        "startup": None, "normal_exit": False, "worker_exit_code": None,
        "ocr_operations": 0, "ocr_workflows_status": "NOT_RUN", "public_release_allowed": False,
        "exception": None,
    }
    api = None
    process = None
    with log_path.open("x", encoding="utf-8") as log:
        try:
            os.environ["TEMP"] = str(temporary)
            os.environ["TMP"] = str(temporary)
            tempfile.tempdir = str(temporary)
            sys.path.insert(0, str(data / "plugins"))
            module = importlib.import_module(PLUGIN_ID + ".api")
            if Path(module.__file__).absolute() != (plugin / "api.py").absolute():
                raise ValueError("载入的不是候选插件 API")
            api = module.Api({"device": device})
            message = api.start({"taskType": "document"})
            log.write(json.dumps({"operation": "start", "result": message}, ensure_ascii=False) + "\n")
            log.flush()
            if message:
                raise RuntimeError(message)
            process = api._worker.process
            if process is None or process.poll() is not None:
                raise RuntimeError("实际 worker 未保持运行")
            arguments = process.args
            if not isinstance(arguments, (list, tuple)) or Path(arguments[0]).absolute() != launcher.absolute():
                raise RuntimeError("未通过候选原生入口启动 worker")
            state = api.get_status()
            if state.get("state") != "loaded":
                raise RuntimeError("候选 API 未报告引擎已加载")
            validate_startup(state.get("startup"), process.pid, data, device)
            result["startup"] = dict(state["startup"])
            result["worker_pid"] = process.pid
            log.write(json.dumps({"startup": result["startup"]}, ensure_ascii=False) + "\n")
        except Exception:
            result["exception"] = traceback.format_exc()
            log.write(result["exception"] + "\n")
        finally:
            if api is not None:
                try:
                    release = api.release()
                    result["release_result"] = release
                    if process is not None:
                        result["worker_exit_code"] = process.returncode
                        result["normal_exit"] = process.returncode == 0
                    unloaded = api.get_status()
                    if unloaded.get("state") != "unloaded" or unloaded.get("startup"):
                        raise RuntimeError("退出后仍残留已加载状态或旧启动证据")
                except Exception:
                    result["shutdown_exception"] = traceback.format_exc()
            tempfile.tempdir = temporary_before
            for key, value in environment_before.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            loaded = sorted({name.split(".", 1)[0] for name in sys.modules} & PROPRIETARY_MODULES)
            result["host_loaded_proprietary_modules"] = loaded
            unchanged = sources == file_hashes(plugin, adapter=True) and models == file_hashes(plugin / "models") and launcher_hash == digest(launcher) and lock_hash == digest(lock)
            result["execution_inputs_unchanged"] = unchanged
            result["worker_diagnostics"] = [{"path": str(path), "sha256": digest(path)} for path in sorted(temporary.glob("umi-ocr-cuda-worker-*.log"))]
            if result["startup"] and result["normal_exit"] and not result["exception"] and not result.get("shutdown_exception") and not loaded and unchanged:
                result["status"] = "PASS"
            log.write(json.dumps({"status": result["status"], "normal_exit": result["normal_exit"], "ocr_operations": 0}, ensure_ascii=False) + "\n")
    result["startup_log"] = {"path": str(log_path), "sha256": digest(log_path)}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--expected-parent-acp", type=int, choices=(936, 65001), required=True)
    parser.add_argument("--device", default="gpu:0")
    args = parser.parse_args()
    result = record(args.staging_root, args.output, args.log, args.expected_parent_acp, args.device)
    print(json.dumps({key: result[key] for key in ("status", "plugin_version", "parent_native_code_page", "normal_exit", "ocr_operations", "public_release_allowed")}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
