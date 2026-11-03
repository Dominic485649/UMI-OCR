"""Private GPU OCR worker.  It is the only process that imports Paddle/OpenCV."""

from __future__ import annotations

import base64
import gc
import json
import os
import sys
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
VENDOR = PLUGIN_DIR / "vendor"
MODELS_DIR = PLUGIN_DIR / "models"
os.environ["PADDLE_PDX_DISABLE_DEVICE_FALLBACK"] = "True"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "False"
sys.path.insert(0, str(PLUGIN_DIR))
from runtime_archive_bootstrap import prepare_archives
_runtime_archive_paths = prepare_archives(PLUGIN_DIR)
sys.path[0:0] = [*_runtime_archive_paths, str(VENDOR)]
from i18n_helpers import tr
_dll_handles = []
if os.name == "nt":
    for path in [VENDOR / "paddle" / "base", *sorted((VENDOR / "nvidia").glob("*") if (VENDOR / "nvidia").is_dir() else [])]:
        bin_path = path / "bin"
        candidate = bin_path if bin_path.is_dir() else path
        if candidate.is_dir():
            os.environ["PATH"] = str(candidate) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                _dll_handles.append(os.add_dll_directory(str(candidate)))

_engine = None
_config = None


def reply(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def assert_cuda(device):
    import paddle

    if not paddle.is_compiled_with_cuda():
        raise RuntimeError(tr('当前 Paddle 不是 CUDA 构建；拒绝 CPU fallback'))
    index = int(str(device).split(":", 1)[1])
    if index >= paddle.device.cuda.device_count():
        raise RuntimeError(tr('请求 {device}，但没有对应的 NVIDIA GPU', device=device))
    paddle.device.set_device(device)
    tensor = paddle.to_tensor([1.0], place=paddle.CUDAPlace(index))
    if float((tensor + 1.0).numpy()[0]) != 2.0:
        raise RuntimeError(tr('CUDA 张量自检失败'))


def create_engine(config):
    import cv2
    from paddleocr import PaddleOCR

    cv2.setNumThreads(int(config.get("preprocessThreads", 4)))
    assert_cuda(config["device"])
    det_name = f"{config['detModel']}_det"
    rec_name = f"{config['recModel']}_rec"
    model_dirs = {
        "doc_orientation_classify_model_dir": MODELS_DIR / "PP-LCNet_x1_0_doc_ori_infer",
        "doc_unwarping_model_dir": MODELS_DIR / "UVDoc_grid_infer",
        "textline_orientation_model_dir": MODELS_DIR / "PP-LCNet_x1_0_textline_ori_infer",
        "text_detection_model_dir": MODELS_DIR / f"{det_name}_infer",
        "text_recognition_model_dir": MODELS_DIR / f"{rec_name}_infer",
    }
    required = [model_dirs["text_detection_model_dir"], model_dirs["text_recognition_model_dir"]]
    if config["docOrientation"]:
        required.append(model_dirs["doc_orientation_classify_model_dir"])
    if config["useDocUnwarping"]:
        required.append(model_dirs["doc_unwarping_model_dir"])
    if config["useTextlineOrientation"]:
        required.append(model_dirs["textline_orientation_model_dir"])
    missing = [str(path) for path in required if not path.is_dir()]
    if missing:
        raise FileNotFoundError(tr('缺少离线模型目录：{items}', items=', '.join(missing)))
    return PaddleOCR(
        doc_orientation_classify_model_name="PP-LCNet_x1_0_doc_ori",
        doc_unwarping_model_name="UVDoc",
        text_detection_model_name=det_name,
        textline_orientation_model_name="PP-LCNet_x1_0_textline_ori",
        text_recognition_model_name=rec_name,
        use_doc_orientation_classify=bool(config["docOrientation"]),
        use_doc_unwarping=bool(config["useDocUnwarping"]),
        use_textline_orientation=bool(config["useTextlineOrientation"]),
        text_det_limit_side_len=int(config["longSide"]),
        text_det_limit_type="max",
        text_recognition_batch_size=int(config["recBatchSize"]),
        text_rec_score_thresh=float(config["scoreThreshold"]),
        device=config["device"],
        engine="paddle",
        enable_hpi=False,
        use_tensorrt=False,
        enable_mkldnn=False,
        **{key: str(path) for key, path in model_dirs.items()},
    )


def decode_request(request):
    import cv2
    import numpy as np
    from io import BytesIO
    from PIL import Image
    from image_tiles import check_size, MAX_IMAGE_BYTES
    from i18n_helpers import tr

    if request["op"] == "run_path":
        source = Path(str(request["path"]))
        if source.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError(tr("输入图片文件超过大小预算。"))
        raw = source.read_bytes()
    else:
        encoded = str(request.get("data", ""))
        if len(encoded) > (MAX_IMAGE_BYTES + 2) // 3 * 4:
            raise ValueError(tr("输入图片文件超过大小预算。"))
        raw = base64.b64decode(encoded, validate=True)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(tr("输入图片文件超过大小预算。"))
    # 先核对解码尺寸，避免先分配整个超大像素缓冲再应用检测长边限制。
    with Image.open(BytesIO(raw)) as header:
        check_size(*header.size)
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(tr("图片无法由 OpenCV 解码。"))
    check_size(image.shape[1], image.shape[0])
    return image


def convert_results(results):
    from coordinates import restore_polygon

    items = []
    for result in results:
        texts = result.get("rec_texts", [])
        scores = result.get("rec_scores", [])
        polygons = result.get("rec_polys", [])
        preprocessor = result.get("doc_preprocessor_res")
        use_unwarping = result.get("model_settings", {}).get("use_doc_unwarping", False)
        if use_unwarping and (preprocessor is None or preprocessor.get("grid") is None):
            raise RuntimeError(tr('UVDoc 网格输出不可用'))
        has_transform = preprocessor is not None and preprocessor.get("input_img") is not None
        for text, score, polygon in zip(texts, scores, polygons):
            box = restore_polygon(polygon, preprocessor) if has_transform else [[int(round(x)), int(round(y))] for x, y in polygon]
            items.append({"text": str(text), "box": box, "score": float(score)})
    return {"code": 100, "data": items} if items else {"code": 101, "data": ""}


def predict_image(image, config, timeout):
    from image_tiles import tiles, merge
    from i18n_helpers import tr
    height, width = image.shape[:2]
    regions = tiles(width, height, config["longSide"])
    deadline = time.monotonic() + timeout
    blocks, warnings = [], []
    completed = 0
    for index, (x1, y1, x2, y2) in enumerate(regions):
        if time.monotonic() >= deadline:
            warnings.append(tr("处理时间预算已用尽，保留已完成的分块。"))
            break
        try:
            result = convert_results(_engine.predict(image[y1:y2, x1:x2]))
            items = result.get("data") or []
            available = max(0, 20000 - len(blocks))
            for item in items[:available]:
                item["box"] = [[x + x1, y + y1] for x, y in item["box"]]
                blocks.append(item)
            completed += 1
            if len(items) > available:
                warnings.append(tr("识别结果数量超过预算，保留已完成的分块。"))
                break
        except Exception as exc:
            warnings.append(tr("第 {index} 个分块识别失败：{error}", index=index + 1, error=str(exc)))
    result = {"code": 100, "data": merge(blocks)} if blocks else {"code": 101, "data": ""}
    if warnings:
        result.update({"partial": True, "warnings": warnings})
        if not blocks:
            result.update({"code": 204, "data": "\n".join(warnings)})
    result["metadata"] = {"sourceWidth": width, "sourceHeight": height,
                          "tileCount": len(regions), "completedTiles": completed}
    return result


def stop_engine():
    global _engine, _config
    engine = _engine
    _engine = None
    _config = None
    if engine is not None:
        try:
            engine.close()
        except Exception:
            pass
        del engine
        gc.collect()


def _configure_stdio():
    # Direct launches may inherit a legacy PYTHONIOENCODING even when the
    # interpreter uses UTF-8 mode. Keep JSON stdout and diagnostic stderr
    # separate, and preserve their existing error-handling policies.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors=stream.errors)


def startup_info(config):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetACP.restype = wintypes.UINT
    kernel32.GetModuleFileNameW.argtypes = (wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
    kernel32.GetModuleFileNameW.restype = wintypes.DWORD
    code_page = int(kernel32.GetACP())
    if code_page != 65001 or not sys.flags.utf8_mode:
        raise RuntimeError(tr('CUDA worker 必须由原生 UTF-8 入口启动；需要 Windows 10 1903 或更新系统。'))
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetModuleFileNameW(sys.dllhandle, buffer, len(buffer))
    if not length or length >= len(buffer):
        raise OSError(tr('无法确认实际 Python DLL 路径。'))
    models = []
    if config["docOrientation"]:
        models.append("PP-LCNet_x1_0_doc_ori")
    if config["useDocUnwarping"]:
        models.append("UVDoc")
    if config["useTextlineOrientation"]:
        models.append("PP-LCNet_x1_0_textline_ori")
    models.extend((f"{config['detModel']}_det", f"{config['recModel']}_rec"))
    return {
        "pid": os.getpid(), "native_code_page": code_page,
        "python_utf8_mode": bool(sys.flags.utf8_mode),
        "stdin_encoding": sys.stdin.encoding, "stdout_encoding": sys.stdout.encoding,
        "python_version": sys.version.split()[0], "python_dll": buffer.value,
        "executable": sys.executable, "model_names": models, "device": config["device"],
    }


def main():
    global _engine, _config
    _configure_stdio()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            op = request.get("op")
            if op == "start":
                stop_engine()
                started = time.perf_counter_ns()
                _config = dict(request.get("config") or {})
                startup = startup_info(_config)
                _engine = create_engine(_config)
                startup["runtime_archives"] = list(_runtime_archive_paths)
                startup["archive_modules"] = {
                    name: str(module.__file__) for name, module in tuple(sys.modules.items())
                    if getattr(module, "__file__", None) and any(
                        str(module.__file__).replace("\\", "/").startswith(path.replace("\\", "/") + "/")
                        for path in _runtime_archive_paths)
                }
                reply({"ok": True, "status": "loaded", "model_initialization_ms": (time.perf_counter_ns() - started) / 1_000_000, "startup": startup})
            elif op in {"run_path", "run_bytes"}:
                if _engine is None:
                    raise RuntimeError("worker engine is not initialized")
                started = time.perf_counter_ns()
                image = decode_request(request)
                decode_ms = (time.perf_counter_ns() - started) / 1_000_000
                started = time.perf_counter_ns()
                result = predict_image(image, _config, float(request.get("taskTimeoutSeconds", 300)))
                predict_ms = (time.perf_counter_ns() - started) / 1_000_000
                reply({"ok": True, "result": result, "timing": {"decode_ms": round(decode_ms, 3), "predict_ms": round(predict_ms, 3), "total_ms": round(decode_ms + predict_ms, 3)}})
            elif op == "stop":
                stop_engine()
                reply({"ok": True, "status": "stopped"})
                return
            else:
                raise ValueError(f"unknown worker operation: {op}")
        except Exception as exc:
            from i18n_helpers import tr
            code = str(exc)
            messages = {
                "IMAGE_BUDGET_EXCEEDED": tr("图片尺寸超过安全解码预算，请裁剪或降低原图尺寸。"),
                "IMAGE_TILE_BUDGET_EXCEEDED": tr("图片需要的分块数量过多，请分成较小图片后重试。"),
            }
            error_type = code if code in messages else "INFERENCE_FAILED"
            if "out of memory" in code.lower():
                error_type = "OUT_OF_MEMORY"
            reply({"ok": False, "error": messages.get(code, code), "errorType": error_type})


if __name__ == "__main__":
    main()
