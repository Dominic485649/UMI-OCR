import argparse
import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def _sample_rgb(np):
    y, x = np.indices((72, 96))
    return np.stack(
        ((x * 255 // 95), (y * 255 // 71), ((x + y) * 255 // 166)), axis=-1
    ).astype(np.uint8)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    handles = configure_runtime(data_root)

    import imagecodecs
    import numpy as np
    from PIL import AvifImagePlugin, Image, ImageOps
    from py_src.mission.mission_ocr import ImageSuf
    # 本测试属于 base 档：只验证图像解码，不依赖任何 OCR 后端。
    # 引擎侧「未 start 时拒绝解码」的断言在 test_ocr_workflows.py（combined 档）。
    from py_src.utils.image_decoder import (
        ImageDecodeError,
        decode_image_bgr,
        decode_image_pil,
    )

    rgb = _sample_rgb(np)
    encoded = {}
    stream = io.BytesIO()
    Image.fromarray(rgb).save(
        stream, "AVIF", quality=100, subsampling="4:4:4", codec="aom"
    )
    encoded[".avif"] = stream.getvalue()
    stream = io.BytesIO()
    Image.fromarray(rgb).save(stream, "WEBP", lossless=True)
    encoded[".webp"] = stream.getvalue()
    encoded[".jxl"] = imagecodecs.jpegxl_encode(rgb, lossless=True)
    encoded[".jxr"] = imagecodecs.jpegxr_encode(rgb)

    expected_bgr = np.ascontiguousarray(rgb[:, :, ::-1])
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        for suffix, data in encoded.items():
            path = directory / f"sample{suffix}"
            path.write_bytes(data)
            for source in (path, data):
                decoded = decode_image_bgr(source)
                assert decoded.dtype == np.uint8
                assert decoded.flags.c_contiguous
                assert decoded.shape == expected_bgr.shape
                delta = np.abs(decoded.astype(np.int16) - expected_bgr.astype(np.int16))
                if suffix == ".avif":
                    assert float(delta.mean()) < 2.0 and int(delta.max()) <= 8
                else:
                    assert int(delta.max()) == 0

        for suffix in (".wdp", ".hdp"):
            path = directory / f"sample{suffix}"
            path.write_bytes(encoded[".jxr"])
            assert np.array_equal(decode_image_bgr(path), expected_bgr)

    assert AvifImagePlugin.DECODE_CODEC_CHOICE == "dav1d"
    assert AvifImagePlugin._avif.decoder_codec_available("dav1d")
    assert imagecodecs.JPEGXL.available and imagecodecs.JPEGXR.available
    assert {".avif", ".webp", ".jxl", ".jxr", ".wdp", ".hdp"} <= set(ImageSuf)

    rgb10 = np.rint(rgb.astype(np.float64) * (1023.0 / 255.0)).astype(np.uint16)
    jxl10 = imagecodecs.jpegxl_encode(rgb10, lossless=True, bitspersample=10)
    assert np.max(
        np.abs(decode_image_bgr(jxl10).astype(np.int16) - expected_bgr.astype(np.int16))
    ) <= 1

    rgba = np.array([[[255, 0, 0, 0], [255, 0, 0, 128]]], dtype=np.uint8)
    stream = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(stream, "PNG")
    alpha = decode_image_bgr(stream.getvalue())
    assert alpha[0, 0].tolist() == [255, 255, 255]
    assert max(abs(a - b) for a, b in zip(alpha[0, 1], [127, 127, 255])) <= 1
    assert decode_image_pil(encoded[".jxl"]).mode == "RGB"

    portrait = Image.fromarray(rgb[:48, :72])
    exif = portrait.getexif()
    exif[274] = 6
    stream = io.BytesIO()
    portrait.save(stream, "JPEG", quality=100, subsampling=0, exif=exif)
    expected = np.asarray(ImageOps.exif_transpose(Image.open(io.BytesIO(stream.getvalue()))))
    expected = np.ascontiguousarray(expected[:, :, ::-1])
    oriented = decode_image_bgr(stream.getvalue())
    assert oriented.shape == expected.shape
    assert np.max(np.abs(oriented.astype(np.int16) - expected.astype(np.int16))) <= 2

    try:
        decode_image_bgr(b"")
    except ImageDecodeError:
        pass
    else:
        raise AssertionError("empty input must fail")

    print(
        "Image decoder tests passed: "
        f"dav1d {AvifImagePlugin.get_codec_version('dav1d')}, "
        f"{imagecodecs.jpegxl_version()}, {imagecodecs.jpegxr_version()}."
    )
    del handles


if __name__ == "__main__":
    main()
