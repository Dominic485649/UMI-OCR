import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    handles = configure_runtime(data_root)

    import numpy as np

    module_path = (
        data_root / "plugins" / "win32_PaddleOCRv6_CUDA" / "coordinates.py"
    )
    spec = importlib.util.spec_from_file_location("uvdoc_coordinates", module_path)
    coordinates = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = coordinates
    spec.loader.exec_module(coordinates)

    xs = np.linspace(-1.0, 1.0, 120, dtype=np.float32)
    ys = np.linspace(-1.0, 1.0, 80, dtype=np.float32)
    gx, gy = np.meshgrid(xs, ys)
    image = np.zeros((80, 120, 3), dtype=np.uint8)
    result = {
        "angle": 0,
        "input_img": image,
        "rot_img": image,
        "grid": np.stack([gx, gy], axis=-1)[None],
    }
    polygon = [[10, 12], [90, 12], [90, 60], [10, 60]]
    assert coordinates.restore_polygon(polygon, result) == polygon

    image = np.zeros((40, 80, 3), dtype=np.uint8)
    rotated = np.zeros((80, 40, 3), dtype=np.uint8)
    result = {"angle": 90, "input_img": image, "rot_img": rotated, "grid": None}
    assert coordinates.restore_polygon([[20, 40]], result) == [[40, 20]]

    del handles
    print("UVDoc coordinate tests passed.")


if __name__ == "__main__":
    main()
