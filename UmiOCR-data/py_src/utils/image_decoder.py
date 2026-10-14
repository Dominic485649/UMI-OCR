from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps


class ImageDecodeError(ValueError):
    pass


_AVIF_SUFFIXES = {".avif"}
_JXL_SUFFIXES = {".jxl"}
_JXR_SUFFIXES = {".jxr", ".wdp", ".hdp"}


def decode_image_bgr(source):
    """Decode a path or encoded bytes to contiguous BGR uint8 pixels."""
    data, suffix = _read_source(source)
    format_ = _detect_format(data, suffix)
    try:
        if format_ == "avif":
            image = _decode_with_pillow(data, require_avif=True)
            return _to_bgr8(image, "rgb")
        if format_ in {"jxl", "jxr"}:
            image = _decode_with_imagecodecs(data, format_)
            return _to_bgr8(image, "rgb")

        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if image is not None:
            image = _apply_exif_orientation(image, data)
            return _to_bgr8(image, "bgr")
        return _to_bgr8(_decode_with_pillow(data), "rgb")
    except ImageDecodeError:
        raise
    except Exception as exc:
        raise ImageDecodeError(f"无法解码 {format_.upper()} 图片：{exc}") from exc


def decode_image_pil(source):
    bgr = decode_image_bgr(source)
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), "RGB")


def _read_source(source):
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
        suffix = ""
    elif isinstance(source, (str, Path)):
        path = Path(source)
        suffix = path.suffix.lower()
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ImageDecodeError(f"无法读取图片：{path}：{exc}") from exc
    else:
        raise TypeError(f"图片输入必须是路径或字节，不能是 {type(source).__name__}。")
    if not data:
        raise ImageDecodeError("图片数据为空。")
    return data, suffix


def _detect_format(data, suffix):
    if suffix in _AVIF_SUFFIXES:
        return "avif"
    if suffix in _JXL_SUFFIXES:
        return "jxl"
    if suffix in _JXR_SUFFIXES:
        return "jxr"
    if len(data) >= 12 and data[4:8] == b"ftyp" and (
        data[8:12] in {b"avif", b"avis"} or b"avif" in data[12:32]
    ):
        return "avif"
    if data.startswith(b"\xff\x0a") or data.startswith(
        b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a"
    ):
        return "jxl"
    if data.startswith(b"II\xbc\x01") or data.startswith(b"MM\x01\xbc"):
        return "jxr"
    return "image"


def _decode_with_pillow(data, require_avif=False):
    if require_avif:
        from PIL import AvifImagePlugin

        if not AvifImagePlugin.SUPPORTED or not AvifImagePlugin._avif.decoder_codec_available(
            "dav1d"
        ):
            raise ImageDecodeError("AVIF 解码器 dav1d 不可用。")
        AvifImagePlugin.DECODE_CODEC_CHOICE = "dav1d"

    with Image.open(BytesIO(data)) as image:
        if require_avif and image.format != "AVIF":
            raise ImageDecodeError("文件不是有效的 AVIF 图片。")
        image = ImageOps.exif_transpose(image)
        if image.has_transparency_data:
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, "white")
            image = Image.alpha_composite(background, rgba).convert("RGB")
        else:
            image = image.convert("RGB")
        return np.asarray(image)


def _decode_with_imagecodecs(data, format_):
    try:
        import imagecodecs
    except ImportError as exc:
        raise ImageDecodeError(
            "JPEG XL/JPEG XR 解码组件 imagecodecs 未安装或损坏。"
        ) from exc
    decoder = imagecodecs.jpegxl_decode if format_ == "jxl" else imagecodecs.jpegxr_decode
    image = decoder(data)
    if image is None:
        raise ImageDecodeError(f"{format_.upper()} 解码器未返回图像。")
    return image


def _apply_exif_orientation(image, data):
    try:
        with Image.open(BytesIO(data)) as metadata:
            orientation = metadata.getexif().get(274, 1)
    except Exception:
        return image
    if orientation == 2:
        return cv2.flip(image, 1)
    if orientation == 3:
        return cv2.rotate(image, cv2.ROTATE_180)
    if orientation == 4:
        return cv2.flip(image, 0)
    if orientation == 5:
        return cv2.transpose(image)
    if orientation == 6:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if orientation == 7:
        return cv2.flip(cv2.transpose(image), -1)
    if orientation == 8:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def _to_bgr8(image, channel_order):
    image = np.asarray(image)
    if image.ndim not in {2, 3}:
        raise ImageDecodeError(f"不支持的图像维度：{image.shape}。")
    image = _to_uint8(image)
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    channels = image.shape[2]
    if channels == 1:
        return cv2.cvtColor(image[:, :, 0], cv2.COLOR_GRAY2BGR)
    if channels not in {3, 4}:
        raise ImageDecodeError(f"不支持的通道数：{channels}。")

    color = image[:, :, :3]
    if channels == 4:
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        color = np.rint(color * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
    if channel_order == "rgb":
        color = color[:, :, ::-1]
    return np.ascontiguousarray(color)


def _to_uint8(image):
    if image.dtype == np.uint8:
        return image
    if image.dtype == np.bool_:
        return image.astype(np.uint8) * 255
    if np.issubdtype(image.dtype, np.unsignedinteger):
        maximum = np.iinfo(image.dtype).max
        if image.dtype == np.uint16 and image.size:
            # libjxl keeps 10/12-bit code values in a uint16 array.
            peak = int(np.max(image))
            if peak <= 1023:
                maximum = 1023
            elif peak <= 4095:
                maximum = 4095
        return np.rint(image.astype(np.float64) * (255.0 / maximum)).astype(np.uint8)
    if np.issubdtype(image.dtype, np.signedinteger):
        info = np.iinfo(image.dtype)
        scaled = (image.astype(np.float64) - info.min) * (255.0 / (info.max - info.min))
        return np.rint(scaled).astype(np.uint8)
    if np.issubdtype(image.dtype, np.floating):
        finite = np.nan_to_num(image, nan=0.0, posinf=1.0, neginf=0.0)
        if finite.size and float(np.max(finite)) > 1.0:
            finite = finite / 255.0
        return np.rint(np.clip(finite, 0.0, 1.0) * 255.0).astype(np.uint8)
    raise ImageDecodeError(f"不支持的像素类型：{image.dtype}。")
