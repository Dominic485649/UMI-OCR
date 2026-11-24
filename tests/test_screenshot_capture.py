import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    output_path = args.output.resolve() if args.output else None
    handles = configure_runtime(data_root)
    sys.path.insert(0, str(data_root / "py_src" / "imports"))

    from PySide6.QtGui import QColorSpace, QGuiApplication
    from py_src.image_controller.hdr_capture import HdrCapture
    from py_src.image_controller.image_provider import PixmapProvider
    from py_src.image_controller.screenshot_controller import ScreenshotController

    app = QGuiApplication.instance() or QGuiApplication([])
    captures = ScreenshotController.getScreenshot(0, 0, 0)
    assert len(captures) == len(QGuiApplication.screens()) and captures
    summary = []
    for capture in captures:
        assert not capture["imgID"].startswith("["), capture
        assert capture["width"] > 0 and capture["height"] > 0
        assert capture["captureMode"] in {"hdr-wgc-d3d11", "sdr-qscreen"}
        pixmap = PixmapProvider.getPixmap(capture["imgID"])
        assert pixmap and pixmap.width() == capture["width"]
        if capture["captureMode"] == "hdr-wgc-d3d11":
            assert pixmap.toImage().colorSpace() == QColorSpace(
                QColorSpace.NamedColorSpace.SRgb
            )
        if output_path and not summary:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            assert pixmap.save(str(output_path), "PNG")
        summary.append(
            {
                "screen": capture["screenName"],
                "mode": capture["captureMode"],
                "size": [capture["width"], capture["height"]],
                "sdrWhiteNits": capture["sdrWhiteNits"],
                "peakNits": capture["peakNits"],
            }
        )
        PixmapProvider.delPixmap(capture["imgID"])

    repeated = ScreenshotController.getScreenshot(0, 0, 0)
    assert [(item["screenName"], item["width"], item["height"]) for item in repeated] == [
        (item["screen"], item["size"][0], item["size"][1]) for item in summary
    ]
    for item in repeated:
        assert not item["imgID"].startswith("["), item
        PixmapProvider.delPixmap(item["imgID"])

    original_capture = HdrCapture.capture
    try:
        def fail_hdr(*_args, **_kwargs):
            raise RuntimeError("forced HDR initialization failure")

        HdrCapture.capture = fail_hdr
        fallback = ScreenshotController.getScreenshot(0, 0, 0)
        assert fallback and all(item["captureMode"] == "sdr-qscreen" for item in fallback)
        assert all(not item["imgID"].startswith("[") for item in fallback)
        for item in fallback:
            PixmapProvider.delPixmap(item["imgID"])
    finally:
        HdrCapture.capture = original_capture

    del app, handles
    print(
        json.dumps(
            {"captures": summary, "repeatedCapture": True, "forcedFallback": True},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
