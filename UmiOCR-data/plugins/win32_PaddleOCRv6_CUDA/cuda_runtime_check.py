"""worker 内的 CUDA 兼容检查；仅依赖标准库，不在宿主导入 Paddle。"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re


class CudaCheckError(RuntimeError):
    def __init__(self, error_type, message, details):
        super().__init__(message)
        self.error_type = error_type
        self.details = dict(details)


def _translate(text, **values):
    return text.format(**values)


def _version(value):
    try:
        return str(value() if callable(value) else value)
    except Exception:
        return "unknown"


def load_support(path, *, tr=None, expected_sha256=None):
    """覆盖记录来自构建期原生检查；启动不重扫大型 DLL。"""
    tr = tr or _translate
    path = Path(path)
    try:
        with path.open("rb") as stream:
            raw = stream.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise ValueError("support record exceeds budget")
        if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("support record differs from the frozen runtime")
        record = json.loads(raw)
        if not isinstance(record, dict) or record.get("schema_version") != 1:
            raise ValueError("unsupported support-record schema")
        providers = record.get("providers")
        if not isinstance(providers, list) or not 1 <= len(providers) <= 16:
            raise ValueError("invalid provider list")
        for provider in providers:
            if not isinstance(provider, dict) or not isinstance(provider.get("path"), str):
                raise ValueError("invalid provider")
            if not re.fullmatch(r"[0-9a-f]{64}", provider.get("sha256", "")):
                raise ValueError("invalid provider digest")
            for key in ("cubins", "ptx"):
                targets = provider.get(key)
                if not isinstance(targets, list) or len(targets) > 64 or any(
                    not isinstance(target, str) or not re.fullmatch(r"\d{2,4}[af]?", target)
                    for target in targets
                ):
                    raise ValueError("invalid provider targets")
        if not all(isinstance(record.get(key), str) and record[key] for key in ("paddle_version", "cuda_version")):
            raise ValueError("missing runtime identity")
        return record
    except Exception as exc:
        raise CudaCheckError(
            "GPU_SUPPORT_RECORD_INVALID",
            tr("GPU 兼容记录缺失或损坏，请完整重新安装匹配的插件。"),
            {"supportRecord": str(path), "reason": str(exc)},
        ) from exc


def _target_supports(target, capability, *, ptx):
    match = re.fullmatch(r"(\d{2,4})([af]?)", target)
    if not match:
        return None
    value, feature = int(match[1]), match[2]
    if feature:
        # 架构/家族特化代码不当成通用前向兼容；交给真实自检判定。
        return None
    if ptx:
        return capability >= value
    return capability // 10 == value // 10 and capability % 10 >= value % 10


def provider_supports(provider, capability):
    decisions = [
        _target_supports(target, capability, ptx=ptx)
        for key, ptx in (("cubins", False), ("ptx", True))
        for target in provider[key]
    ]
    if any(value is True for value in decisions):
        return True
    return None if any(value is None for value in decisions) else False


def check_cuda(paddle, device, support, *, tr=None, run_tensor=True):
    tr = tr or _translate
    details = {
        "device": str(device), "paddle": str(getattr(paddle, "__version__", "unknown")),
        "cuda": _version(getattr(paddle.version, "cuda", "unknown")),
        "cudnn": _version(getattr(paddle.version, "cudnn", "unknown")),
        "selfTest": "NOT_RUN",
    }

    def fail(code, text, **values):
        raise CudaCheckError(code, tr(text, **values), details)

    if not paddle.is_compiled_with_cuda():
        fail("CUDA_BUILD_REQUIRED", "当前 Paddle 不是 CUDA 构建；拒绝 CPU fallback")
    match = re.fullmatch(r"gpu:(\d+)", str(device))
    if not match:
        fail("INVALID_CUDA_DEVICE", "CUDA 设备必须使用 gpu:N 格式，例如 gpu:0。")
    index = int(match[1])
    count = int(paddle.device.cuda.device_count())
    details["deviceCount"] = count
    if index >= count:
        fail("CUDA_DEVICE_UNAVAILABLE", "请求 {device}，但没有对应的 NVIDIA GPU", device=device)
    try:
        major, minor = paddle.device.cuda.get_device_capability(index)
        details["deviceName"] = str(paddle.device.cuda.get_device_name(index))
    except Exception as exc:
        details["nativeError"] = str(exc)[:4000]
        fail("CUDA_DEVICE_QUERY_FAILED", "无法读取 CUDA 设备信息：{error}", error=str(exc))
    capability = int(major) * 10 + int(minor)
    details["computeCapability"] = f"{major}.{minor}"
    details["providers"] = [
        {"path": item["path"], "cubins": item["cubins"], "ptx": item["ptx"]}
        for item in support["providers"]
    ]
    if support["paddle_version"] != details["paddle"] or support["cuda_version"] != details["cuda"]:
        fail("GPU_RUNTIME_RECORD_MISMATCH", "Paddle/CUDA 版本与插件兼容记录不匹配，请完整重新安装插件。")
    unavailable = [
        item["path"] for item in support["providers"]
        if provider_supports(item, capability) is False
    ]
    if unavailable:
        details["unsupportedProviders"] = unavailable
        fail(
            "UNSUPPORTED_GPU_ARCHITECTURE",
            "当前插件不支持 {name}（算力 {capability}），核心运行库没有兼容的 GPU 代码；重装系统 CUDA 无法解决。",
            name=details["deviceName"], capability=details["computeCapability"],
        )
    if not run_tensor:
        return details
    try:
        details["phase"] = "set_device"
        paddle.device.set_device(device)
        details["phase"] = "scalar_add"
        tensor = paddle.to_tensor([1.0], dtype="float32", place=paddle.CUDAPlace(index))
        result = tensor + 1.0
        details["phase"] = "synchronize"
        paddle.device.cuda.synchronize(index)
        details["phase"] = "copy_to_cpu"
        actual = float(result.numpy()[0])
        details.update({"actual": repr(actual), "expected": 2.0})
    except Exception as exc:
        details["selfTest"] = "FAILED"
        details["nativeError"] = str(exc)[:4000]
        fail("CUDA_SELF_TEST_EXECUTION_FAILED", "CUDA 基础计算失败：{error}", error=str(exc))
    if not math.isfinite(actual) or actual != 2.0:
        details["selfTest"] = "FAILED"
        fail("CUDA_SELF_TEST_RESULT_INVALID", "CUDA 张量自检失败：预期 2.0，实际为 {actual}。", actual=repr(actual))
    details.pop("phase", None)
    details["selfTest"] = "PASSED"
    return details
