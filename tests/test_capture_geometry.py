import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "UmiOCR-data" / "py_src" / "image_controller" / "capture_geometry.py"
spec = importlib.util.spec_from_file_location("capture_geometry", MODULE)
capture_geometry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture_geometry)


def main():
    map_rect = capture_geometry.logical_to_physical_rect
    assert map_rect(0, 0, 1536, 864, 1.25, 1.25, 1920, 1080) == (
        0,
        0,
        1920,
        1080,
    )
    assert map_rect(10.2, 20.1, 100, 50, 1.25, 1.25, 1920, 1080) == (
        12,
        25,
        126,
        63,
    )
    assert map_rect(10, 10, 1, 1, 1.5, 2.0, 3840, 2160) == (15, 20, 2, 2)
    assert map_rect(-5, -5, 20, 20, 2.0, 2.0, 3840, 2160) == (0, 0, 30, 30)

    negative_virtual_x = -1920
    global_x = -1910
    assert map_rect(global_x - negative_virtual_x, 4, 10, 6, 1.0, 1.0, 1920, 1080) == (
        10,
        4,
        10,
        6,
    )
    print("Mixed-DPI half-open screenshot coordinate tests passed.")


if __name__ == "__main__":
    main()
