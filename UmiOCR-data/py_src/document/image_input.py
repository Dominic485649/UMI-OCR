"""宿主统一的文档图片输入；源文件保持不变，跨进程只交付普通无损图片。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile
import time

from ..utils.image_decoder import ImageDecodeError, decode_image_pil

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_PIXELS = 32_000_000
MAX_IMAGE_SIDE = 32_000
MAX_PREPARED_BYTES = 128 * 1024 * 1024


def check_source(source):
    size = Path(source).stat().st_size
    if not 0 < size <= MAX_FILE_BYTES:
        raise ImageDecodeError("INPUT_FILE_BUDGET：输入须为非空且不超过 64 MiB。")


def check_size(width, height):
    if not (0 < width <= MAX_IMAGE_SIDE and 0 < height <= MAX_IMAGE_SIDE and width * height <= MAX_IMAGE_PIXELS):
        raise ImageDecodeError("IMAGE_DECODE_BUDGET：图片超过 32000 单边或 3200 万像素预算。")


def image_frame(source, index=0):
    """返回独立 RGB 帧和帧数；TIFF 保留逐页，其他编码与图片 OCR 一样取首帧。"""
    from PIL import Image, ImageOps
    source = Path(source)
    check_source(source)
    if source.suffix.lower() in {".tif", ".tiff"}:
        with Image.open(source) as image:
            count = int(getattr(image, "n_frames", 1))
            if not 0 <= index < count:
                raise ImageDecodeError("文档图片页号超出范围。")
            image.seek(index)
            check_size(*image.size)
            oriented = ImageOps.exif_transpose(image)
            try:
                rgba = oriented.convert("RGBA")
                try:
                    background = Image.new("RGBA", rgba.size, "white")
                    try:
                        normalized = Image.alpha_composite(background, rgba)
                        try:
                            return normalized.convert("RGB"), count
                        finally:
                            normalized.close()
                    finally:
                        background.close()
                finally:
                    rgba.close()
            finally:
                if oriented is not image:
                    oriented.close()
    if index != 0:
        raise ImageDecodeError("此图片仅提供首帧，页号须为 1。")
    image = decode_image_pil(source, max_pixels=MAX_IMAGE_PIXELS, max_side=MAX_IMAGE_SIDE)
    check_size(*image.size)
    return image, 1


class _BoundedWriter:
    def __init__(self, stream):
        self.stream = stream
    def write(self, value):
        if self.stream.tell() + len(value) > MAX_PREPARED_BYTES:
            raise ImageDecodeError("IMAGE_DECODE_BUDGET：规范化图片超过 128 MiB。")
        return self.stream.write(value)
    def fileno(self):
        raise OSError("bounded image output has no direct descriptor")
    def __getattr__(self, key):
        return getattr(self.stream, key)


@contextmanager
def prepared_document_input(source, work_root, deadline, cancelled=None, *, single_frame=False):
    source = Path(source).resolve()
    check_source(source)
    def check_deadline():
        if cancelled and cancelled():
            raise ImageDecodeError("文档解析已取消。")
        if time.monotonic() >= deadline:
            raise TimeoutError("TASK_DEADLINE：输入图片规范化超出任务预算。")
    check_deadline()
    if source.suffix.lower() == ".pdf" or (not single_frame and source.suffix.lower() in {".tif", ".tiff"}):
        yield {"path": str(source), "prepared": False}
        return
    root = Path(tempfile.mkdtemp(prefix="document-input-", dir=work_root))
    target = root / "input.png"
    try:
        image, _count = image_frame(source)
        try:
            check_deadline()
            with target.open("xb") as stream:
                image.save(_BoundedWriter(stream), format="PNG")
        finally:
            image.close()
        check_deadline()
        yield {"path": str(target), "prepared": True}
    finally:
        # 仅清理此上下文创建的单个规范化文件；出现未知文件时不递归删除。
        target.unlink(missing_ok=True)
        root.rmdir()
