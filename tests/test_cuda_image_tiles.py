"""无推理依赖的大图覆盖、坐标合并与资源边界测试。"""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/image_tiles.py"
spec = importlib.util.spec_from_file_location("cuda_image_tiles", SOURCE)
tiles_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tiles_module)


class CudaImageTileTests(unittest.TestCase):
    def test_single_image_keeps_original_region(self):
        self.assertEqual(tiles_module.tiles(1000, 800, 4000), [(0, 0, 1000, 800)])

    def test_long_image_is_fully_covered(self):
        regions = tiles_module.tiles(1200, 12000, 4000)
        self.assertEqual(regions[0][1], 0)
        self.assertEqual(regions[-1][3], 12000)
        for previous, current in zip(regions, regions[1:]):
            self.assertLess(current[1], previous[3])

    def test_giant_pixel_buffer_is_rejected_before_decode(self):
        for size in ((0, 10), (50001, 1), (10000, 10000)):
            with self.assertRaises(ValueError):
                tiles_module.check_size(*size)

    def test_result_budget_is_strict_and_reports_omission(self):
        worker_path = SOURCE.with_name("worker.py")
        worker_spec = importlib.util.spec_from_file_location("cuda_worker_result_budget", worker_path)
        worker = importlib.util.module_from_spec(worker_spec)
        worker_spec.loader.exec_module(worker)
        class Image:
            shape = (800, 800, 3)
            def __getitem__(self, _):
                return self
        for count in (20000, 20001):
            with self.subTest(count=count):
                values = [{"text": str(index), "score": 1.0,
                           "box": [[0, 0], [10, 0], [10, 10], [0, 10]]} for index in range(count)]
                with patch.object(worker, "_engine", Mock()), \
                     patch.object(worker, "convert_results", return_value={"code": 100, "data": values}):
                    result = worker.predict_image(Image(), {"longSide": 4000}, 10)
                self.assertEqual(result["code"], 100)
                self.assertEqual(len(result["data"]), 20000)
                self.assertEqual(bool(result.get("partial")), count > 20000)
                self.assertEqual(bool(result.get("warnings")), count > 20000)

    def test_spatial_duplicate_does_not_remove_repeated_text_elsewhere(self):
        def block(x, score):
            return {"text": "repeat", "score": score,
                    "box": [[x, 0], [x + 100, 0], [x + 100, 20], [x, 20]]}
        values = tiles_module.merge([block(0, 0.8), block(3, 0.9), block(500, 0.7)])
        self.assertEqual(len(values), 2)
        self.assertEqual(values[0]["score"], 0.9)


if __name__ == "__main__":
    unittest.main()
