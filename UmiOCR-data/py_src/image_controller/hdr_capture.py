import ctypes
import sys
from pathlib import Path

from PySide6.QtGui import QColorSpace, QImage


class _CaptureResult(ctypes.Structure):
    _fields_ = [
        ("pixels", ctypes.c_void_p),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("stride", ctypes.c_uint32),
        ("used_hdr", ctypes.c_uint32),
        ("sdr_white_nits", ctypes.c_float),
        ("peak_nits", ctypes.c_float),
    ]


class NativeHdrCapture:
    _NOT_HDR = 1

    def __init__(self):
        self._dll = None
        self._load_error = None

    def _load(self):
        if self._dll:
            return self._dll
        if self._load_error:
            raise RuntimeError(self._load_error)
        if sys.platform != "win32":
            self._load_error = "HDR capture is only available on Windows."
            raise RuntimeError(self._load_error)
        path = Path.cwd() / "native" / "UmiOCR-HdrCapture.dll"
        try:
            dll = ctypes.WinDLL(str(path))
            dll.UmiHdrCaptureAbiVersion.restype = ctypes.c_uint32
            if dll.UmiHdrCaptureAbiVersion() != 1:
                raise RuntimeError("Unsupported UmiOCR-HdrCapture ABI version.")
            dll.UmiCaptureMonitorHdr.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_float,
                ctypes.c_float,
                ctypes.POINTER(_CaptureResult),
                ctypes.POINTER(ctypes.c_wchar),
                ctypes.c_uint32,
            ]
            dll.UmiCaptureMonitorHdr.restype = ctypes.c_int32
            dll.UmiFreeCapture.argtypes = [ctypes.c_void_p]
            dll.UmiFreeCapture.restype = None
            self._dll = dll
        except (OSError, RuntimeError) as error:
            self._load_error = f"Native HDR capture unavailable ({path.name}): {error}"
            raise RuntimeError(self._load_error) from error
        return self._dll

    def capture(self, display_name, sdr_white_nits=0.0, peak_nits=0.0):
        dll = self._load()
        result = _CaptureResult()
        error = ctypes.create_unicode_buffer(1024)
        status = dll.UmiCaptureMonitorHdr(
            display_name,
            float(sdr_white_nits),
            float(peak_nits),
            ctypes.byref(result),
            error,
            len(error),
        )
        if status == self._NOT_HDR:
            return None
        if status != 0:
            raise RuntimeError(error.value or f"Native HDR capture failed with status {status}.")
        if not result.pixels or not result.width or not result.height:
            raise RuntimeError("Native HDR capture returned an empty image.")
        try:
            data = ctypes.string_at(result.pixels, result.stride * result.height)
            image = QImage(
                data,
                result.width,
                result.height,
                result.stride,
                QImage.Format.Format_RGBA8888,
            ).copy()
        finally:
            dll.UmiFreeCapture(result.pixels)
        if image.isNull():
            raise RuntimeError("Qt could not create an image from the HDR capture result.")
        image.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
        return {
            "image": image,
            "mode": "hdr-wgc-d3d11",
            "sdrWhiteNits": float(result.sdr_white_nits),
            "peakNits": float(result.peak_nits),
        }


HdrCapture = NativeHdrCapture()
