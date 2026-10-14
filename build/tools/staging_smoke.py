import argparse
import json
import os
import sys
from pathlib import Path


def _mount_plugin_runtimes(data_root, handles):
    """按 umi-plugin.json 挂载各插件的私有运行时，与生产加载器
    （py_src/plugins_controller/plugins_controller.py 的 _mountRuntime）
    保持同一套规则：vendor 追加到 sys.path 末尾、dll_dirs 支持通配。

    The GPU plugin now keeps its Paddle/NVIDIA stack inside a child worker;
    the smoke test must exercise that same process boundary rather than import
    the proprietary stack into the host test process.
    """
    import glob as _glob

    plugins_root = data_root / "plugins"
    if not plugins_root.is_dir():
        return
    for manifest_path in sorted(plugins_root.glob("*/umi-plugin.json")):
        plugin_dir = manifest_path.parent
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        runtime = manifest.get("runtime") or {}
        for relative in runtime.get("vendor_dirs") or []:
            vendor = plugin_dir / relative
            if vendor.is_dir() and str(vendor) not in sys.path:
                sys.path.append(str(vendor))
        if os.name != "nt":
            continue
        for pattern in runtime.get("dll_dirs") or []:
            for match in sorted(_glob.glob(str(plugin_dir / pattern))):
                if os.path.isdir(match):
                    match = os.path.abspath(match)
                    entries = os.environ.get("PATH", "").split(os.pathsep)
                    if match.casefold() not in {entry.casefold() for entry in entries if entry}:
                        entries.append(match)
                        os.environ["PATH"] = os.pathsep.join(entries)
                    handles.append(os.add_dll_directory(match))


def configure_runtime(data_root):
    site_packages = data_root / "site-packages"
    sys.path[:0] = [
        str(data_root),
        str(site_packages),
        str(data_root / "plugins"),
        str(data_root / "py_src" / "imports"),
        str(data_root / "app.zip"),
        str(data_root / "app.zip" / "py_src" / "imports"),
        str(data_root / "dependencies.zip"),
    ]
    handles = []
    pyside = site_packages / "PySide6"
    if pyside.is_dir():
        handles.append(os.add_dll_directory(pyside))
    _mount_plugin_runtimes(data_root, handles)
    if (data_root / "ui.rcc").is_file():
        from PySide6.QtCore import QResource
        assert QResource.registerResource(str(data_root / "ui.rcc"))
    os.chdir(data_root)
    return handles


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--device", default="gpu:0")
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    handles = configure_runtime(data_root)

    import cv2
    import numpy as np
    import PySide6
    from win32_PaddleOCRv6_CUDA.api import Api

    about = json.loads((data_root / "about.json").read_text("utf-8"))
    version = about["version"]
    version_text = f"{version['major']}.{version['minor']}.{version['patch']}"

    if "paddle" in sys.modules:
        raise RuntimeError("host smoke process imported Paddle; GPU stack must remain in worker")

    engine = Api({"device": args.device, "preprocessThreads": 2})
    error = engine.start({"taskType": "screenshot"})
    if error:
        raise RuntimeError(error)
    if "paddle" in sys.modules:
        raise RuntimeError("host smoke process imported Paddle after worker startup")
    image = np.full((800, 1600, 3), 255, dtype=np.uint8)
    cv2.putText(
        image,
        f"Umi-OCR {version_text}",
        (50, 400),
        cv2.FONT_HERSHEY_SIMPLEX,
        5.0,
        (0, 0, 0),
        12,
        cv2.LINE_AA,
    )
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("failed to encode smoke-test image")
    results = {}
    for task_type in ("screenshot", "document"):
        # The synthetic smoke image is flat text, so do not ask UVDoc to
        # unwarp it; the real document/PDF workflow exercises UVDoc separately.
        error = engine.start({"taskType": task_type, "undistort": "off", "textlineOrientation": "off"})
        if error:
            raise RuntimeError(error)
        result = engine.runBytes(encoded.tobytes())
        if result.get("code") != 100:
            raise RuntimeError(f"PP-OCRv6 medium {task_type} inference failed (shape={image.shape}, bytes={len(encoded)}): {result}")
        for item in result["data"]:
            if set(item) != {"text", "box", "score"} or len(item["box"]) != 4:
                raise RuntimeError(f"invalid OCR result contract: {item}")
        results[task_type] = result
    engine.stop()

    print(
        json.dumps(
            {
                "python": sys.version.split()[0],
                "qt": PySide6.__version__,
                "paddle": "worker-only",
                "cuda_device": args.device,
                "cuda_devices": "verified by worker CUDA initialization",
                "ocr_items": {
                    task: len(result["data"]) for task, result in results.items()
                },
                "texts": {
                    task: [item["text"] for item in result["data"]]
                    for task, result in results.items()
                },
                "fallback": False,
                "architecture": "separate-worker-stdio-ipc",
            },
            ensure_ascii=False,
        )
    )
    del handles


if __name__ == "__main__":
    main()
