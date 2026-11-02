import argparse
import io
import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def _measure(func, process, warmups=3, runs=10):
    for _ in range(warmups):
        func()
    timings = []
    peak = process.memory_info().rss
    for _ in range(runs):
        started = time.perf_counter_ns()
        image = func()
        timings.append((time.perf_counter_ns() - started) / 1_000_000)
        info = process.memory_info()
        peak = max(peak, getattr(info, "peak_wset", info.rss))
        if image is None or image.size == 0:
            raise RuntimeError("decoder returned an empty image")
    timings.sort()
    return {
        "median_ms": round(statistics.median(timings), 3),
        "p95_ms": round(timings[math.ceil(len(timings) * 0.95) - 1], 3),
        "peak_process_mib": round(peak / 1048576, 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    output_path = args.output.resolve() if args.output else None
    handles = configure_runtime(data_root)

    import cv2
    import imagecodecs
    import numpy as np
    import psutil
    from PIL import AvifImagePlugin, Image
    from py_src.utils.image_decoder import decode_image_bgr

    y, x = np.indices((1200, 1600))
    rgb = np.stack(
        ((x * 255 // 1599), (y * 255 // 1199), ((x + y) * 255 // 2798)), axis=-1
    ).astype(np.uint8)
    stream = io.BytesIO()
    Image.fromarray(rgb).save(
        stream, "AVIF", quality=90, subsampling="4:4:4", codec="aom"
    )
    avif = stream.getvalue()
    stream = io.BytesIO()
    Image.fromarray(rgb).save(stream, "WEBP", lossless=True)
    webp = stream.getvalue()
    jxl = imagecodecs.jpegxl_encode(rgb, lossless=True)
    jxr = imagecodecs.jpegxr_encode(rgb)
    process = psutil.Process()

    def pillow(data):
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return np.asarray(image.convert("RGB"))

    AvifImagePlugin.DECODE_CODEC_CHOICE = "dav1d"
    cases = {
        "avif/pillow-dav1d": lambda: pillow(avif),
        "avif/shared-bgr": lambda: decode_image_bgr(avif),
        "webp/opencv": lambda: cv2.imdecode(
            np.frombuffer(webp, np.uint8), cv2.IMREAD_COLOR
        ),
        "webp/pillow": lambda: pillow(webp),
        "webp/imagecodecs": lambda: imagecodecs.webp_decode(webp),
        "webp/shared-bgr": lambda: decode_image_bgr(webp),
        "jxl/imagecodecs": lambda: imagecodecs.jpegxl_decode(jxl),
        "jxl/shared-bgr": lambda: decode_image_bgr(jxl),
        "jxr/imagecodecs": lambda: imagecodecs.jpegxr_decode(jxr),
        "jxr/shared-bgr": lambda: decode_image_bgr(jxr),
    }
    report = {
        "image": {"width": 1600, "height": 1200},
        "method": {"warmups": 3, "runs": 10, "summary": "median and P95"},
        "codecs": {
            "dav1d": AvifImagePlugin.get_codec_version("dav1d"),
            "webp": imagecodecs.webp_version(),
            "jpegxl": imagecodecs.jpegxl_version(),
            "jpegxr": imagecodecs.jpegxr_version(),
        },
        "results": {name: _measure(func, process) for name, func in cases.items()},
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    del handles


if __name__ == "__main__":
    main()
