"""Run real CUDA workflow tests and bind their evidence to the exact inputs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ID = "win32_PaddleOCRv6_CUDA"


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def plugin_source_hashes(plugin):
    return {
        path.relative_to(plugin).as_posix(): digest(path)
        for path in sorted(plugin.rglob("*.py"))
        if not any(part in {"vendor", "models", "__pycache__"} for part in path.relative_to(plugin).parts)
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--device", default="gpu:0")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    staging = args.staging_root.resolve()
    repo = args.repo_root.resolve()
    data = staging / "UmiOCR-data"
    plugin = data / "plugins" / PLUGIN_ID
    runtime = data / "runtime/python.exe"
    test = repo / "tests/test_ocr_workflows.py"
    output = args.output.resolve()
    log = args.log.resolve()
    if output.exists() or log.exists():
        raise RuntimeError("Use new evidence and log paths; existing evidence must not be overwritten")
    if not log.parent.is_dir() or not output.parent.is_dir():
        raise RuntimeError("Evidence/log parent directories must already exist")
    lock = plugin / "runtime.lock.json"
    if not runtime.is_file() or not lock.is_file() or not test.is_file():
        raise RuntimeError("Candidate runtime, lock and real workflow test are required")
    source_before = plugin_source_hashes(plugin)
    lock_before = digest(lock)
    test_before = digest(test)
    environment = os.environ.copy()
    environment["PADDLE_PDX_DISABLE_DEVICE_FALLBACK"] = "True"
    environment["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    process = subprocess.run(
        [str(runtime), "-B", "-I", "-S", "-X", "utf8", str(test), str(data), "--device", args.device],
        cwd=staging, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=900,
    )
    log.write_text(process.stdout, encoding="utf-8")
    print(process.stdout)
    if process.returncode != 0:
        raise RuntimeError(f"Actual GPU workflows failed with exit {process.returncode}; no PASS evidence written")
    expected_result = "OCR workflow tests passed: batch=2, PDF=2 pages, layered PDF, JXL QR, "
    if expected_result not in process.stdout:
        raise RuntimeError("Actual workflow output did not confirm the expected paths")
    if source_before != plugin_source_hashes(plugin) or lock_before != digest(lock) or test_before != digest(test):
        raise RuntimeError("Workflow inputs changed during verification")
    vendor = plugin / "vendor"
    if any(vendor.glob("cv2/opencv_videoio_ffmpeg*.dll")):
        raise RuntimeError("Excluded FFmpeg backend is present")
    if any(vendor.rglob("cusolverMg64_11.dll")):
        raise RuntimeError("Excluded cuSolverMg runtime is present")
    record = {
        "test_type": "real_gpu_ocr_workflows_e2e",
        "status": "PASS",
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "device": args.device,
        "architecture": {
            "type": "separate-worker-stdio-ipc",
            "host_loaded_proprietary_modules": [],
            "ipc_payload": "JSON-lines path/base64 -> JSON OCR result",
        },
        "plugin_runtime_lock_sha256": lock_before,
        "plugin_source_sha256": source_before,
        "workflow_test": {"path": "tests/test_ocr_workflows.py", "SHA256": test_before},
        "workflow_log": {"file": log.name, "SHA256": digest(log)},
        "model_initialization": [
            "PP-LCNet_x1_0_doc_ori", "UVDoc", "PP-LCNet_x1_0_textline_ori",
            "PP-OCRv6_medium_det", "PP-OCRv6_medium_rec",
        ],
        "ffmpeg_backend_dll_count": 0,
        "cusolvermg_dll_count": 0,
        "exercised_paths": ["batch OCR", "document PDF OCR", "CUDA-only failure paths"],
    }
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print("Fresh GPU workflow evidence written:", output)


if __name__ == "__main__":
    main()
