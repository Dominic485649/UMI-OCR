import argparse
import importlib.metadata
import io
import json
import math
import os
import statistics
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def _measure(func, process, warmups=3, runs=10):
    for _ in range(warmups):
        func()
    timings = []
    for _ in range(runs):
        started = time.perf_counter_ns()
        func()
        timings.append((time.perf_counter_ns() - started) / 1_000_000)
    timings.sort()
    memory = process.memory_info()
    return {
        "median_ms": round(statistics.median(timings), 3),
        "p95_ms": round(timings[math.ceil(len(timings) * 0.95) - 1], 3),
        "peak_process_mib": round(getattr(memory, "peak_wset", memory.rss) / 1048576, 2),
    }


def _comparison(baseline, candidate):
    comparison = {}
    failed = []
    for name, result in candidate["results"].items():
        before = baseline["results"][name]
        time_change = result["median_ms"] / before["median_ms"] - 1.0
        memory_change = result["peak_process_mib"] / before["peak_process_mib"] - 1.0
        passed = time_change <= 0.10 and memory_change <= 0.15
        comparison[name] = {
            "median_change_percent": round(time_change * 100, 2),
            "peak_memory_change_percent": round(memory_change * 100, 2),
            "passed": passed,
        }
        if not passed:
            failed.append(name)
    candidate["comparison"] = comparison
    return failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--override", type=Path)
    parser.add_argument("--label", default="candidate")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    override = args.override.resolve() if args.override else None
    baseline_path = args.baseline.resolve() if args.baseline else None
    output_path = args.output.resolve() if args.output else None
    handles = configure_runtime(data_root)

    if override:
        sys.path.insert(0, str(override))
        if handles:
            handles[0].close()
        handles[0] = os.add_dll_directory(str(override / "PySide6"))

    import fitz
    import psutil
    import zxingcpp
    from PIL import Image
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QUrl, qVersion
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    process = psutil.Process()
    pixels = bytes((index * 37) % 256 for index in range(1600 * 1200 * 3))
    source_image = Image.frombytes("RGB", (1600, 1200), pixels)
    png_stream = io.BytesIO()
    source_image.save(png_stream, "PNG", compress_level=3)
    png = png_stream.getvalue()

    def pillow_decode():
        with Image.open(io.BytesIO(png)) as image:
            image.load()
            return image.getpixel((800, 600))

    pdf = fitz.open()
    for page_index in range(5):
        page = pdf.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Umi-OCR PDF benchmark page {page_index}", fontsize=24)
    pdf_bytes = pdf.tobytes()
    pdf.close()

    def pymupdf_render():
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            pixmap = document[2].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            return pixmap.samples[0]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        barcode = zxingcpp.write_barcode(
            zxingcpp.BarcodeFormat.QRCode, "Umi-OCR zxing benchmark", 1000, 1000
        )

    def zxing_decode():
        result = zxingcpp.read_barcodes(barcode)
        if not result or result[0].text != "Umi-OCR zxing benchmark":
            raise RuntimeError("zxing correctness failed")

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication.instance() or QGuiApplication(["runtime-benchmark"])
    engine = QQmlEngine()
    qml_root = (
        override / "PySide6" / "qml"
        if override
        else data_root / "site-packages" / "PySide6" / "qml"
    )
    engine.addImportPath(str(qml_root))
    qml = b"""
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Item { RowLayout { Button { text: "Umi-OCR" } } }
"""

    def qml_create():
        for _ in range(20):
            component = QQmlComponent(engine)
            component.setData(qml, QUrl("inline:runtime-benchmark.qml"))
            while component.isLoading():
                app.processEvents()
            obj = component.create()
            if obj is None:
                raise RuntimeError(component.errorString())
            obj.deleteLater()
        app.processEvents()

    report = {
        "label": args.label,
        "method": {"warmups": 3, "runs": 10, "summary": "median and P95"},
        "versions": {
            "python": sys.version.split()[0],
            "qt": qVersion(),
            "pyside6": pyside_version,
            "pillow": Image.__version__,
            "pymupdf": fitz.VersionBind,
            "zxing_cpp": importlib.metadata.version("zxing-cpp"),
        },
        "results": {
            "pyside6_qml_create": _measure(qml_create, process),
            "pillow_png_decode": _measure(pillow_decode, process),
            "pymupdf_page_render": _measure(pymupdf_render, process),
            "zxing_cpp_decode": _measure(zxing_decode, process),
        },
    }
    failed = []
    if baseline_path:
        baseline = json.loads(baseline_path.read_text("utf-8"))
        failed = _comparison(baseline, report)

    output = json.dumps(report, ensure_ascii=False, indent=2)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")
    print(output)
    del engine, app, handles
    if failed:
        raise RuntimeError("dependency benchmark regression: " + ", ".join(failed))


if __name__ == "__main__":
    main()
