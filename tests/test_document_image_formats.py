"""图片格式经过宿主解码、任务规范化与文档预览的真实定向验证。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    data, work = args.data.resolve(), args.work.resolve()
    if work.exists(): raise FileExistsError(work)
    work.mkdir()
    os.chdir(work)
    sys.path[:0] = [str(ROOT / "UmiOCR-data"), str(ROOT / "UmiOCR-data/py_src/imports"),
                   str(data / "site-packages"), str(data / "dependencies.zip")]
    handles = [os.add_dll_directory(str(data / "site-packages/PySide6"))]
    import imagecodecs
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from PySide6.QtGui import QGuiApplication
    from py_src.document.image_input import image_frame, prepared_document_input
    from py_src.utils.image_decoder import ImageDecodeError
    from py_src.utils.image_formats import IMAGE_SUFFIXES, DOCUMENT_SUFFIXES, document_name_filter
    from py_src.mission.mission_ocr import ImageSuf
    from py_src.mission.mission_document import DocumentSuf
    from py_src.mission.doc_preview_connector import DocPreviewConnector
    from py_src.image_controller.image_provider import PixmapProvider
    from py_src.utils.thread_pool import GlobalThreadPool

    app = QGuiApplication([])
    fixtures = work / "输入 图片"
    fixtures.mkdir()
    normalized = work / "normalized"
    normalized.mkdir()
    rgb = Image.new("RGB", (600, 280), "white")
    draw = ImageDraw.Draw(rgb)
    font = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts/msyh.ttc"), 35)
    draw.text((30, 35), "Umi-OCR 3.1.2", font=font, fill="black")
    draw.text((30, 120), "统一图片格式 12345", font=font, fill="black")
    encoded = {}
    for suffix, format_ in ((".png", "PNG"), (".jpg", "JPEG"), (".webp", "WEBP"), (".avif", "AVIF"), (".bmp", "BMP"), (".tiff", "TIFF")):
        path = fixtures / ("测试" + suffix)
        options = {"quality": 100} if format_ in {"JPEG", "AVIF"} else {"lossless": True} if format_ == "WEBP" else {}
        rgb.save(path, format_, **options)
        encoded[suffix] = path
    encoded[".jxl"] = fixtures / "测试.jxl"
    encoded[".jxl"].write_bytes(imagecodecs.jpegxl_encode(np.asarray(rgb), lossless=True))
    encoded[".jxr"] = fixtures / "测试.jxr"
    encoded[".jxr"].write_bytes(imagecodecs.jpegxr_encode(np.asarray(rgb)))
    for alias, suffix in ((".wdp", ".jxr"), (".hdp", ".jxr"), (".jpeg", ".jpg"), (".jpe", ".jpg"), (".jfif", ".jpg"), (".tif", ".tiff")):
        path = fixtures / ("测试" + alias)
        path.write_bytes(encoded[suffix].read_bytes())
        encoded[alias] = path
    for bits in (10, 12):
        path = fixtures / f"高位深{bits}位.JXL"
        pixels = np.rint(np.asarray(rgb).astype(np.float64) * ((2 ** bits - 1) / 255)).astype(np.uint16)
        path.write_bytes(imagecodecs.jpegxl_encode(pixels, lossless=True, bitspersample=bits))
        encoded[f"jxl-{bits}bit"] = path
    assert set(ImageSuf) == set(IMAGE_SUFFIXES)
    assert set(DocumentSuf) == set(DOCUMENT_SUFFIXES) == set(IMAGE_SUFFIXES) | {".pdf"}
    assert all("*" + suffix in document_name_filter() for suffix in IMAGE_SUFFIXES)
    results = []
    for suffix, source in encoded.items():
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        frame, count = image_frame(source)
        assert count == 1 and frame.size == rgb.size
        if suffix.startswith("jxl-"):
            assert np.abs(np.asarray(frame).astype(np.int16) - np.asarray(rgb).astype(np.int16)).max() <= 1
        frame.close()
        with prepared_document_input(source, normalized, time.monotonic() + 20) as prepared:
            with Image.open(prepared["path"]) as image:
                assert image.size == rgb.size and image.mode == "RGB"
            temporary = Path(prepared["path"])
        if prepared["prepared"]: assert not temporary.exists()
        connector = DocPreviewConnector()
        infos, images = [], []
        connector.previewInfo.connect(infos.append)
        connector.previewImg.connect(images.append)
        connector.preview(str(source), 1, "")
        deadline = time.monotonic() + 10
        while not images:
            app.processEvents()
            assert time.monotonic() < deadline, suffix
            time.sleep(0.001)
        assert infos[-1]["pageCount"] == 1 and infos[-1]["width"] == rgb.width, infos
        assert not images[-1].startswith("["), images
        pixmap = PixmapProvider.getPixmap(images[-1])
        assert pixmap.width() == rgb.width and pixmap.height() == rgb.height
        connector.clear()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
        results.append({"suffix": source.suffix.lower(), "case": suffix, "source": str(source), "sourceSha256": before, "previewSize": [pixmap.width(), pixmap.height()]})
    # EXIF 旋转与白底透明合成必须在预览和规范化中一致。
    rotated = fixtures / "方向.JPG"
    exif = rgb.getexif(); exif[274] = 6
    rgb.save(rotated, "JPEG", exif=exif)
    image, _ = image_frame(rotated)
    assert image.size == (rgb.height, rgb.width)
    image.close()
    transparent = fixtures / "透明.png"
    Image.new("RGBA", (16, 12), (255, 0, 0, 0)).save(transparent)
    image, _ = image_frame(transparent)
    assert image.getpixel((0, 0)) == (255, 255, 255)
    image.close()
    multi = fixtures / "多页.tiff"
    second = Image.new("RGB", (80, 50), "white")
    rgb.save(multi, save_all=True, append_images=[second])
    image, count = image_frame(multi, 1)
    assert count == 2 and image.size == second.size
    image.close()
    corrupt = fixtures / "损坏.jxl"
    corrupt.write_bytes(b"not an image")
    try:
        image_frame(corrupt)
    except ImageDecodeError:
        pass
    else:
        raise AssertionError("损坏输入不能伪装成无文字")
    from unittest.mock import patch
    from py_src.utils.image_decoder import decode_image_pil
    with patch.dict(sys.modules, {"imagecodecs": None}):
        try:
            image_frame(encoded[".jxl"])
        except ImageDecodeError:
            pass
        else:
            raise AssertionError("缺少 codec 不得伪装成空白图片")
    try:
        decode_image_pil(encoded[".png"], max_pixels=100)
    except ImageDecodeError:
        pass
    else:
        raise AssertionError("解码像素预算未生效")
    for deadline, cancelled, error in ((time.monotonic() - 1, None, TimeoutError),
                                       (time.monotonic() + 20, lambda: True, ImageDecodeError)):
        try:
            with prepared_document_input(encoded[".png"], normalized, deadline, cancelled):
                raise AssertionError("取消／已过期任务不应进行规范化")
        except error:
            pass
    assert not list(normalized.iterdir())
    GlobalThreadPool.waitForDone(10000)
    report = {"passed": True, "formats": results, "checks": ["统一格式集合", "真实解码与PNG规范化", "原始像素预览", "JXL 10/12位归一化", "缺失codec拒绝", "解码像素预算", "EXIF旋转", "透明白底", "多帧TIFF", "损坏拒绝", "源文件不变", "自有临时文件清理"]}
    (work / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "formats": len(results), "result": str(work / "result.json")}, ensure_ascii=False))
    del handles


if __name__ == "__main__":
    main()
