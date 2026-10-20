# ==================================================
# =============== PP-OCRv6 CUDA 健康检查 ===============
# ==================================================

"""Cheap host-side health check for the separate GPU OCR worker.

The host process deliberately does not import Paddle, OpenCV, or any NVIDIA
library.  Those modules are loaded only by ``worker.py`` in the independent
worker process.  A real CUDA/device check therefore happens during worker
initialisation and is covered by the GPU E2E evidence; this function only
checks that the release artifact contains the complete worker closure.
"""

from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
MODELS_DIR = PLUGIN_DIR / "models"
VENDOR_DIR = PLUGIN_DIR / "vendor"
RUNTIME_LOCK = PLUGIN_DIR / "runtime.lock.json"
WORKER = PLUGIN_DIR / "worker.py"

# 缺任何一个模型目录，OCR 都无法启动。
REQUIRED_MODEL_DIRS = (
    "PP-OCRv6_medium_det_infer",
    "PP-OCRv6_medium_rec_infer",
    "UVDoc_grid_infer",
    "PP-LCNet_x1_0_doc_ori_infer",
    "PP-LCNet_x1_0_textline_ori_infer",
)


def _checkModels():
    return [
        name
        for name in REQUIRED_MODEL_DIRS
        if not (MODELS_DIR / name / "inference.json").is_file()
    ]


def check():
    details = {
        "pluginDir": str(PLUGIN_DIR),
        "modelsDir": str(MODELS_DIR),
        "architecture": "separate-worker-stdio-ipc",
        "paddleVersion": "worker-only",
        "cudaCheck": "performed by worker initialization",
    }

    missing_models = _checkModels()
    missing_files = [
        str(path.relative_to(PLUGIN_DIR))
        for path in (WORKER, RUNTIME_LOCK)
        if not path.is_file()
    ]
    if not (VENDOR_DIR / "nvidia").is_dir():
        missing_files.append("vendor/nvidia")

    details["missingModels"] = missing_models
    details["missingFiles"] = missing_files
    if missing_models or missing_files:
        missing = missing_models + missing_files
        return {
            "ok": False,
            "message": (
                f"GPU OCR worker 归档不完整，缺少：{', '.join(missing)}。"
                "请重新解压完整 GPU OCR 插件归档。"
            ),
            "details": details,
        }

    return {
        "ok": True,
        "message": (
            "GPU OCR worker 归档完整；实际 Paddle/CUDA/cuDNN 设备检查将在"
            "独立 worker 启动和推理时执行。"
        ),
        "details": details,
    }
