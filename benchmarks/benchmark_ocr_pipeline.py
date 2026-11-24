import argparse
import hashlib
import importlib.metadata
import io
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def _normalize(text):
    return "".join(
        char.lower()
        for char in unicodedata.normalize("NFKC", text)
        if char.isalnum()
    )


def _edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _cer(expected, actual):
    expected = _normalize(expected)
    actual = _normalize(actual)
    return _edit_distance(expected, actual) / max(1, len(expected))


def _rect_iou(expected, polygon):
    ex0, ey0, ex1, ey1 = expected
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    ax0, ay0, ax1, ay1 = min(xs), min(ys), max(xs), max(ys)
    intersection = max(0, min(ex1, ax1) - max(ex0, ax0)) * max(
        0, min(ey1, ay1) - max(ey0, ay0)
    )
    union = (ex1 - ex0) * (ey1 - ey0) + (ax1 - ax0) * (ay1 - ay0) - intersection
    return intersection / union if union > 0 else 0.0


def _font(ImageFont, name, size):
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = {
        "latin": ["arial.ttf", "segoeui.ttf"],
        "cjk": ["msyh.ttc", "msyhbd.ttc"],
        "japanese": ["meiryo.ttc", "YuGothM.ttc", "msyh.ttc"],
    }[name]
    path = next((font_dir / item for item in candidates if (font_dir / item).is_file()), None)
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default()


def _document(Image, ImageDraw, font, lines, foreground="black", table=False):
    image = Image.new("RGB", (1200, max(360, 100 + len(lines) * 100)), "white")
    draw = ImageDraw.Draw(image)
    boxes = []
    if table:
        for x in (30, 390, 720, 1170):
            draw.line((x, 35, x, image.height - 35), fill=(80, 80, 80), width=3)
        for y in range(35, image.height, 100):
            draw.line((30, y, 1170, y), fill=(80, 80, 80), width=3)
    for index, text in enumerate(lines):
        position = (55, 65 + index * 100)
        draw.text(position, text, font=font, fill=foreground)
        box = draw.textbbox(position, text, font=font)
        boxes.append([box[0] - 5, box[1] - 5, box[2] + 5, box[3] + 5])
    return image, boxes


def _encode_png(image):
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def _corpus(Image, ImageDraw, ImageFont, cv2, np):
    cases = []

    def add(name, font_name, size, lines, **kwargs):
        image, boxes = _document(
            Image,
            ImageDraw,
            _font(ImageFont, font_name, size),
            lines,
            **kwargs,
        )
        cases.append(
            {
                "name": name,
                "task": "screenshot",
                "expected": " ".join(lines),
                "boxes": boxes,
                "data": _encode_png(image),
            }
        )
        return image, boxes

    english, english_boxes = add(
        "english", "latin", 64, ["Umi OCR CUDA 2026", "High Accuracy Pipeline"]
    )
    add("chinese", "cjk", 64, ["高精度文字识别测试", "复杂背景文档方向"])
    add("japanese", "japanese", 60, ["高精度文字認識テスト", "文書方向を自動補正"])
    add(
        "dense-small",
        "latin",
        30,
        ["Invoice 2026-0716", "Item CUDA OCR x 12", "Total USD 128.50"],
    )
    add(
        "low-contrast",
        "latin",
        58,
        ["LOW CONTRAST DOCUMENT", "Readable Gray Text 2026"],
        foreground=(145, 145, 145),
    )
    add(
        "table",
        "latin",
        44,
        ["ITEM     QTY     PRICE", "OCR      12      128.50"],
        table=True,
    )

    rotated = english.rotate(180, expand=False)
    width, height = rotated.size
    rotated_boxes = [
        [width - box[2], height - box[3], width - box[0], height - box[1]]
        for box in english_boxes
    ]
    cases.append(
        {
            "name": "rotated-180",
            "task": "screenshot",
            "expected": "Umi OCR CUDA 2026 High Accuracy Pipeline",
            "boxes": rotated_boxes,
            "data": _encode_png(rotated),
        }
    )

    photo, _ = _document(
        Image,
        ImageDraw,
        _font(ImageFont, "latin", 60),
        ["PHONE PHOTO DOCUMENT", "PERSPECTIVE AND CURVE"],
    )
    source = np.asarray(photo)
    h, w = source.shape[:2]
    source_points = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    target_points = np.float32([[70, 35], [w - 100, 0], [w - 20, h - 30], [0, h - 5]])
    matrix = cv2.getPerspectiveTransform(source_points, target_points)
    warped = cv2.warpPerspective(source, matrix, (w, h), borderValue=(255, 255, 255))
    cases.append(
        {
            "name": "photo-perspective",
            "task": "document",
            "expected": "PHONE PHOTO DOCUMENT PERSPECTIVE AND CURVE",
            "boxes": [],
            "data": cv2.imencode(".png", cv2.cvtColor(warped, cv2.COLOR_RGB2BGR))[1].tobytes(),
        }
    )
    return cases


def _percentile(values, percentile):
    values = sorted(values)
    return values[math.ceil(len(values) * percentile) - 1]


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_inventory(models_dir):
    models = []
    for directory in sorted(path for path in models_dir.iterdir() if path.is_dir()):
        files = []
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            files.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
        models.append(
            {
                "name": directory.name,
                "path": str(directory),
                "files": files,
                "total_bytes": sum(item["size"] for item in files),
            }
        )
    return models


def _command_output(arguments):
    try:
        completed = subprocess.run(
            arguments,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {
            "command": arguments,
            "returncode": completed.returncode,
            "output": completed.stdout.strip(),
        }
    except Exception as exc:
        return {"command": arguments, "error": str(exc)}


def _corpus_metadata(cases):
    digest = hashlib.sha256()
    total_bytes = 0
    for case in cases:
        data = case["data"]
        digest.update(case["name"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        total_bytes += len(data)
    return {
        "case_names": [case["name"] for case in cases],
        "case_count": len(cases),
        "encoded_bytes": total_bytes,
        "sha256": digest.hexdigest(),
    }


def _stage_summary(samples):
    return {
        name: {
            "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(_percentile(values, 0.95), 3),
        }
        for name, values in samples.items()
        if values
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--device", default="gpu:0")
    parser.add_argument("--paddle-override", type=Path)
    parser.add_argument("--label", default="candidate")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    paddle_override = (
        args.paddle_override.resolve() if args.paddle_override else None
    )
    baseline_path = args.baseline.resolve() if args.baseline else None
    output_path = args.output.resolve() if args.output else None
    handles = configure_runtime(data_root)
    if paddle_override:
        sys.path.insert(0, str(paddle_override))
        if len(handles) > 1:
            handles[1].close()
            handles[1] = os.add_dll_directory(
                str(paddle_override / "paddle" / "base")
            )

    import cv2
    import numpy as np
    import paddle
    import psutil
    from PIL import Image, ImageDraw, ImageFont
    from win32_PaddleOCRv6_CUDA.api import MODELS_DIR, Api
    from win32_PaddleOCRv6_CUDA.config import PRESETS

    cases = _corpus(Image, ImageDraw, ImageFont, cv2, np)
    representative = next(case["data"] for case in cases if case["name"] == "english")
    process = psutil.Process()
    api = Api({"device": args.device, "preprocessThreads": 4})
    performance = {}
    for preset_name in ("speed", "balanced", "accuracy"):
        config = dict(PRESETS[preset_name])
        config["taskType"] = "screenshot"
        started = time.perf_counter()
        error = api.start(config)
        load_seconds = time.perf_counter() - started
        if error:
            raise RuntimeError(error)
        for _ in range(3):
            result = api.runBytes(representative)
            if result["code"] != 100:
                raise RuntimeError(result)
        paddle.device.cuda.reset_max_memory_allocated(args.device)
        timings = []
        stage_samples = {key: [] for key in ("decode_ms", "predict_ms", "convert_ms")}
        for _ in range(10):
            started = time.perf_counter_ns()
            result = api.runBytes(representative)
            timings.append((time.perf_counter_ns() - started) / 1_000_000)
            if result["code"] != 100:
                raise RuntimeError(result)
            last_timing = api.get_status().get("lastTiming", {})
            for key in stage_samples:
                if key in last_timing:
                    stage_samples[key].append(float(last_timing[key]))
        memory = process.memory_info()
        performance[preset_name] = {
            "engine_load_seconds": round(load_seconds, 3),
            "median_ms": round(statistics.median(timings), 3),
            "p95_ms": round(_percentile(timings, 0.95), 3),
            "peak_process_mib": round(getattr(memory, "peak_wset", memory.rss) / 1048576, 2),
            "peak_gpu_mib": round(
                paddle.device.cuda.max_memory_allocated(args.device) / 1048576, 2
            ),
            "stages": _stage_summary(stage_samples),
        }

    correctness = []
    for task_type in ("screenshot", "document"):
        error = api.start({"taskType": task_type})
        if error:
            raise RuntimeError(error)
        for case in (item for item in cases if item["task"] == task_type):
            result = api.runBytes(case["data"])
            if result["code"] != 100:
                raise RuntimeError(f"{case['name']}: {result}")
            actual = " ".join(item["text"] for item in result["data"])
            ious = [
                max((_rect_iou(box, item["box"]) for item in result["data"]), default=0.0)
                for box in case["boxes"]
            ]
            correctness.append(
                {
                    "name": case["name"],
                    "expected": case["expected"],
                    "actual": actual,
                    "cer": round(_cer(case["expected"], actual), 4),
                    "mean_box_iou": round(statistics.mean(ious), 4) if ious else None,
                    "miss_rate": round(
                        sum(value < 0.1 for value in ious) / len(ious), 4
                    )
                    if ious
                    else None,
                }
            )
    api.stop()

    mean_cer = statistics.mean(item["cer"] for item in correctness)
    box_cases = [item for item in correctness if item["mean_box_iou"] is not None]
    mean_iou = statistics.mean(item["mean_box_iou"] for item in box_cases)
    miss_rate = statistics.mean(item["miss_rate"] for item in box_cases)
    report = {
        "label": args.label,
        "method": {"warmups": 3, "runs": 10, "summary": "median and P95"},
        "device": args.device,
        "versions": {
            "python": sys.version.split()[0],
            "paddle": paddle.__version__,
            "paddleocr": importlib.metadata.version("paddleocr"),
            "paddlex": importlib.metadata.version("paddlex"),
        },
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "physical_memory_mib": round(psutil.virtual_memory().total / 1048576, 2),
            "power_scheme": _command_output(["powercfg", "/getactivescheme"]),
            "gpu": _command_output(
                [
                    "nvidia-smi",
                    "--query-gpu=name,uuid,driver_version,pstate,clocks.sm,"
                    "utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ]
            ),
        },
        "environment": {
            name: os.environ.get(name)
            for name in (
                "CUDA_VISIBLE_DEVICES",
                "PADDLE_PDX_DISABLE_DEVICE_FALLBACK",
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK",
                "PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT",
            )
        },
        "command": {
            "executable": sys.executable,
            "argv": sys.argv,
            "cwd": os.getcwd(),
            "data_root": str(data_root),
            "paddle_override": str(paddle_override) if paddle_override else None,
        },
        "input": _corpus_metadata(cases),
        "models": _model_inventory(MODELS_DIR),
        "performance": performance,
        "correctness": correctness,
        "summary": {
            "mean_cer": round(mean_cer, 4),
            "mean_box_iou": round(mean_iou, 4),
            "mean_miss_rate": round(miss_rate, 4),
        },
    }
    failed = []
    if baseline_path:
        baseline = json.loads(baseline_path.read_text("utf-8"))
        comparison = {}
        for preset_name, result in performance.items():
            previous = baseline["performance"][preset_name]
            time_change = result["median_ms"] / previous["median_ms"] - 1.0
            process_change = (
                result["peak_process_mib"] / previous["peak_process_mib"] - 1.0
            )
            gpu_change = result["peak_gpu_mib"] / previous["peak_gpu_mib"] - 1.0
            passed = (
                time_change <= 0.10
                and process_change <= 0.15
                and gpu_change <= 0.15
            )
            comparison[preset_name] = {
                "median_change_percent": round(time_change * 100, 2),
                "peak_process_memory_change_percent": round(process_change * 100, 2),
                "peak_gpu_memory_change_percent": round(gpu_change * 100, 2),
                "passed": passed,
            }
            if not passed:
                failed.append(preset_name)
        report["comparison"] = comparison
    if mean_cer > 0.35 or mean_iou < 0.25 or miss_rate > 0.35:
        raise RuntimeError(f"OCR correctness threshold failed: {report['summary']}")
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    del handles
    if failed:
        raise RuntimeError("Paddle benchmark regression: " + ", ".join(failed))


if __name__ == "__main__":
    main()
