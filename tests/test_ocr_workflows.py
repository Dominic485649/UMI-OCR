import argparse
import base64
import io
import os
import sys
import tempfile
from pathlib import Path
from threading import Event
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def _make_image(Image, ImageDraw, ImageFont, text):
    image = Image.new("RGB", (1000, 260), "white")
    font_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    font_path = next(
        (path for path in (font_dir / "msyh.ttc", font_dir / "arial.ttf") if path.is_file()),
        None,
    )
    font = ImageFont.truetype(str(font_path), 72) if font_path else ImageFont.load_default()
    ImageDraw.Draw(image).text((40, 75), text, font=font, fill="black")
    return image


def _assert_ocr_result(result):
    assert result["code"] == 100, result
    assert result["data"]
    for item in result["data"]:
        assert {"text", "box", "score"} <= set(item)
        assert len(item["box"]) == 4
        assert all(len(point) == 2 for point in item["box"])
        assert isinstance(item["score"], float)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--device", default="gpu:0")
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    handles = configure_runtime(data_root)

    import fitz
    import imagecodecs
    import importlib.metadata
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from PySide6.QtCore import QCoreApplication
    from py_src.mission.mission_doc import MissionDOC
    from py_src.mission.mission_ocr import MissionOCR
    from py_src.mission.mission_qrcode import MissionQRCode
    from py_src.ocr.output.output_pdf_layered import OutputPdfLayered
    from py_src.plugins_controller.plugins_controller import PluginsController
    from win32_PaddleOCRv6_CUDA.api import Api

    app = QCoreApplication.instance() or QCoreApplication([])
    plugin_key = "win32_PaddleOCRv6_CUDA"
    plugin_info = PluginsController.init()
    assert not plugin_info["errors"], plugin_info["errors"]
    # 插件契约 v2：能力注册表取代了 v1 的内部字典 pluginsDict 。
    assert plugin_key in plugin_info["options"]["ocr"]
    assert not any(name in sys.modules for name in ("paddle","paddleocr","paddlex","onnxruntime")), "inference dependencies must stay in workers"
    states = {p["id"]: p for p in plugin_info["plugins"]}
    assert states[plugin_key]["state"] == "ready", states[plugin_key]
    assert states[plugin_key]["legacy"] is False, "内置 GPU 插件应走 v2 清单路径"
    health = PluginsController.runHealthCheck(plugin_key)
    assert health["ok"], health["message"]
    status = MissionOCR.setApi(
        plugin_key,
        {
            f"ocr.{plugin_key}.device": args.device,
            f"ocr.{plugin_key}.preprocessThreads": 2,
        },
    )
    assert status == "[Success]", status

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)
        images = [
            _make_image(Image, ImageDraw, ImageFont, "Umi OCR CUDA BATCH ONE"),
            _make_image(Image, ImageDraw, ImageFont, "Umi OCR CUDA BATCH TWO"),
        ]
        paths = []
        png_bytes = []
        for index, image in enumerate(images, 1):
            stream = io.BytesIO()
            image.save(stream, "PNG")
            data = stream.getvalue()
            png_bytes.append(data)
            path = temp_dir / f"batch-{index}.png"
            path.write_bytes(data)
            paths.append(path)

        batch = MissionOCR.addMissionWait(
            {"ocr.taskType": "batch", "tbpu.parser": "none"},
            [{"path": str(paths[0])}, {"bytes": png_bytes[1]}],
        )
        assert len(batch) == 2
        for task in batch:
            _assert_ocr_result(task["result"])

        qr = MissionQRCode.createImage("Umi-OCR CUDA QR", w=360, h=360)
        assert not isinstance(qr, str), qr
        qr_rgb = qr.convert("RGB")
        qr_jxl = imagecodecs.jpegxl_encode(np.asarray(qr_rgb), lossless=True)
        qr_path = temp_dir / "qrcode.jxl"
        qr_path.write_bytes(qr_jxl)
        qr_result = MissionQRCode.addMissionWait({}, [{"path": str(qr_path)}])[0][
            "result"
        ]
        assert qr_result["code"] == 100, qr_result
        assert qr_result["data"][0]["text"] == "Umi-OCR CUDA QR"

        source_pdf = temp_dir / "source.pdf"
        document = fitz.open()
        for data in png_bytes:
            page = document.new_page(width=720, height=240)
            page.insert_image(page.rect, stream=data)
        document.save(source_pdf)
        document.close()

        completed = Event()
        pdf_results = []
        end_message = []

        def on_get(_info, page_index, result):
            result["page"] = page_index + 1
            pdf_results.append(result)

        def on_end(_info, message):
            end_message.append(message)
            completed.set()

        mission_id = MissionDOC.addMission(
            {
                "argd": {
                    "doc.extractionMode": "fullPage",
                    "ocr.taskType": "document",
                    "tbpu.parser": "none",
                },
                "onGet": on_get,
                "onEnd": on_end,
            },
            str(source_pdf),
        )
        assert not mission_id.startswith("[Error]"), mission_id
        assert completed.wait(300), "PDF OCR timed out"
        assert end_message == ["[Success]"], end_message
        assert len(pdf_results) == 2
        for result in pdf_results:
            _assert_ocr_result(result)

        output = OutputPdfLayered(
            {
                "outputDir": str(temp_dir),
                "originPath": str(source_pdf),
                "outputFileName": "searchable",
                "password": "",
            }
        )
        try:
            for result in pdf_results:
                output.print(result)
            output.onEnd()
        finally:
            if output.pdf is not None and not output.pdf.is_closed:
                output.pdf.close()
        searchable = temp_dir / "searchable.layered.pdf"
        assert searchable.is_file() and searchable.stat().st_size > 0
        with fitz.open(searchable) as result_pdf:
            assert result_pdf.page_count == 2
            assert all(page.get_text().strip() for page in result_pdf)

    release_message = MissionOCR.releaseModel()
    assert release_message.startswith("[Success]"), release_message
    assert MissionOCR.getStatus()["apiState"]["state"] == "unloaded"
    gpu_vendor = data_root / "plugins" / plugin_key / "vendor"
    if str(gpu_vendor) not in sys.path:
        sys.path.insert(0, str(gpu_vendor))
    assert importlib.metadata.version("paddlepaddle-gpu") == "3.3.1"
    installed = {dist.metadata["Name"].lower() for dist in importlib.metadata.distributions()}
    assert "paddlepaddle" not in installed
    assert "onnxruntime" not in installed and "onnxruntime-directml" not in installed
    worker_source = (data_root / "plugins" / plugin_key / "worker.py").read_text("utf-8")
    assert 'PADDLE_PDX_DISABLE_DEVICE_FALLBACK"] = "True"' in worker_source
    # A real invalid-device start exercises the worker's CUDA-only failure
    # path without importing Paddle into this host process.
    api = Api({"device": "gpu:99", "preprocessThreads": 1})
    error = api.start({"taskType": "screenshot"})
    assert error.startswith("[Error]") and "NVIDIA GPU" in error

    # 引擎在未 start 时必须拒绝推理，且对非图像输入给出解码错误码。
    # 这段原本在 tests/test_image_decoder.py ，但那个测试属于 base 档，
    # 基础包里没有任何 OCR 后端可导入，因此移到这里。
    rgb = np.full((32, 48, 3), 200, dtype=np.uint8)
    jxl_bytes = imagecodecs.jpegxl_encode(rgb, lossless=True)
    jxr_bytes = imagecodecs.jpegxr_encode(rgb)
    idle = Api({"device": args.device, "preprocessThreads": 1})
    assert idle.runBytes(jxl_bytes)["code"] == 203
    assert idle.runBase64(base64.b64encode(jxr_bytes).decode())["code"] == 203
    assert idle.runBytes(b"not an image")["code"] == 203

    assert not any(name in sys.modules for name in ("paddle", "paddleocr", "paddlex", "onnxruntime")), "inference dependencies leaked into the host"
    from py_src.utils.thread_pool import GlobalThreadPool
    assert GlobalThreadPool.waitForDone(5000), "workflow task threads did not finish"
    del app, handles
    print(
        "OCR workflow tests passed: batch=2, PDF=2 pages, layered PDF, JXL QR, "
        "real model release, idle-engine rejection and CUDA-only failure paths."
    )


if __name__ == "__main__":
    main()
