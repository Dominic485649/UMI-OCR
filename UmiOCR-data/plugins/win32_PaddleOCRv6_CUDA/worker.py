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
sys.path.insert(0, str(VENDOR))
if (PLUGIN_DIR / "vendor.zip").is_file():
    sys.path.append(str(PLUGIN_DIR / "vendor.zip"))
sys.path.insert(0, str(PLUGIN_DIR))
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
        raise RuntimeError("当前 Paddle 不是 CUDA 构建；拒绝 CPU fallback")
    index = int(str(device).split(":", 1)[1])
    if index >= paddle.device.cuda.device_count():
        raise RuntimeError(f"请求 {device}，但没有对应的 NVIDIA GPU")
    paddle.device.set_device(device)
    tensor = paddle.to_tensor([1.0], place=paddle.CUDAPlace(index))
    if float((tensor + 1.0).numpy()[0]) != 2.0:
        raise RuntimeError("CUDA 张量自检失败")


def create_engine(config):
    import cv2
    from paddleocr import PaddleOCR

    cv2.setNumThreads(4)
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
        raise FileNotFoundError("缺少离线模型目录：" + ", ".join(missing))
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

    if request["op"] == "run_path":
        image = cv2.imread(str(request["path"]), cv2.IMREAD_COLOR)
    else:
        raw = base64.b64decode(str(request.get("data", "")), validate=True)
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("图片无法由 OpenCV 解码")
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
            raise RuntimeError("UVDoc 网格输出不可用")
        has_transform = preprocessor is not None and preprocessor.get("input_img") is not None
        for text, score, polygon in zip(texts, scores, polygons):
            box = restore_polygon(polygon, preprocessor) if has_transform else [[int(round(x)), int(round(y))] for x, y in polygon]
            items.append({"text": str(text), "box": box, "score": float(score)})
    return {"code": 100, "data": items} if items else {"code": 101, "data": ""}


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


def main():
    global _engine, _config
    for line in sys.stdin:
        try:
            request = json.loads(line)
            op = request.get("op")
            if op == "start":
                stop_engine()
                started = time.perf_counter_ns()
                _config = dict(request.get("config") or {})
                _engine = create_engine(_config)
                reply({"ok": True, "status": "loaded", "model_initialization_ms": (time.perf_counter_ns() - started) / 1_000_000})
            elif op in {"run_path", "run_bytes"}:
                if _engine is None:
                    raise RuntimeError("worker engine is not initialized")
                started = time.perf_counter_ns()
                image = decode_request(request)
                decode_ms = (time.perf_counter_ns() - started) / 1_000_000
                started = time.perf_counter_ns()
                result = convert_results(_engine.predict(image))
                predict_ms = (time.perf_counter_ns() - started) / 1_000_000
                reply({"ok": True, "result": result, "timing": {"decode_ms": round(decode_ms, 3), "predict_ms": round(predict_ms, 3), "total_ms": round(decode_ms + predict_ms, 3)}})
            elif op == "stop":
                stop_engine()
                reply({"ok": True, "status": "stopped"})
                return
            else:
                raise ValueError(f"unknown worker operation: {op}")
        except Exception as exc:
            reply({"ok": False, "error": str(exc)})


if __name__ == "__main__":
    main()
