import argparse
import ctypes
import struct
from pathlib import Path


class CaptureResult(ctypes.Structure):
    _fields_ = [
        ("pixels", ctypes.c_void_p),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("stride", ctypes.c_uint32),
        ("used_hdr", ctypes.c_uint32),
        ("sdr_white_nits", ctypes.c_float),
        ("peak_nits", ctypes.c_float),
    ]


def half_bits(value):
    return struct.unpack("<H", struct.pack("<e", value))[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dll", type=Path)
    args = parser.parse_args()
    dll = ctypes.WinDLL(str(args.dll.resolve()))
    dll.UmiHdrCaptureAbiVersion.restype = ctypes.c_uint32
    assert dll.UmiHdrCaptureAbiVersion() == 1
    dll.UmiToneMapRgba16Float.argtypes = [
        ctypes.POINTER(ctypes.c_uint16),
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_float,
        ctypes.c_float,
        ctypes.POINTER(CaptureResult),
        ctypes.POINTER(ctypes.c_wchar),
        ctypes.c_uint32,
    ]
    dll.UmiToneMapRgba16Float.restype = ctypes.c_int32
    dll.UmiFreeCapture.argtypes = [ctypes.c_void_p]

    def tone_map(levels, white, peak):
        values = []
        for level in levels:
            values.extend((half_bits(level), half_bits(level), half_bits(level), half_bits(1.0)))
        source = (ctypes.c_uint16 * len(values))(*values)
        result = CaptureResult()
        error = ctypes.create_unicode_buffer(1024)
        status = dll.UmiToneMapRgba16Float(
            source,
            len(levels),
            1,
            white,
            peak,
            ctypes.byref(result),
            error,
            len(error),
        )
        assert status == 0, error.value
        try:
            data = ctypes.string_at(result.pixels, result.stride)
        finally:
            dll.UmiFreeCapture(result.pixels)
        return [tuple(data[index : index + 4]) for index in range(0, len(data), 4)]

    sdr = tone_map([0.0, 0.18, 1.0], 80.0, 80.0)
    assert sdr[0] == (0, 0, 0, 255)
    assert 116 <= sdr[1][0] <= 120
    assert sdr[2] == (255, 255, 255, 255)

    levels = [0.0, 1.0, 4.0, 6.25, 10.0, 12.5]
    first = tone_map(levels, 203.0, 1000.0)
    second = tone_map(levels, 203.0, 1000.0)
    assert first == second
    channels = [pixel[0] for pixel in first]
    assert channels == sorted(channels)
    assert channels[0] == 0 and channels[-1] == 255
    assert channels[2] < channels[3] < 255, channels
    assert all(r == g == b and a == 255 for r, g, b, a in first)
    print("D3D11 BT.2390 HDR shader tests passed.")


if __name__ == "__main__":
    main()
