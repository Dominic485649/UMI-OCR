"""HTTP 参数 schema 与联合视觉预算定向回归。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "UmiOCR-data"))
from py_src.server.request_validation import (validate_options, validate_visual_budget,
                                              validate_page_range, InvalidOptions)


class RequestValidationTests(unittest.TestCase):
    definitions = {
        "longSide": {"default": 4000, "isInt": True, "min": 640, "max": 8000},
        "enabled": {"default": True},
        "mode": {"default": "auto", "optionsList": [["auto", "自动"], ["off", "关闭"]]},
        "score": {"default": 0.45, "min": 0, "max": 1, "isInt": False},
    }

    def test_defaults_are_independent(self):
        result = validate_options({}, self.definitions)
        self.assertEqual(result["longSide"], 4000)
        self.assertTrue(result["enabled"])

    def test_reject_unknown_and_global_paths(self):
        for key in ("service.serverExecutable", "pipeline.cudaDevice", "unknown"):
            with self.assertRaises(InvalidOptions):
                validate_options({key: "anything"}, self.definitions)

    def test_reject_invalid_scalar_types_and_ranges(self):
        for values in ({"longSide": True}, {"longSide": 4000.5}, {"longSide": 999999},
                       {"enabled": 1}, {"mode": "invalid"}, {"score": float("nan")},
                       {"score": float("inf")}):
            with self.subTest(values=values), self.assertRaises(InvalidOptions):
                validate_options(values, self.definitions)

    def test_visual_budget_uses_16k_defaults_and_fixed_reserve(self):
        vl = "win32_PaddleOCRVL_1_6"
        validate_visual_budget(vl, {}, 4096)
        validate_visual_budget(vl, {"resources.slots": 2}, 4096)
        validate_visual_budget(vl, {"resources.contextLength": 8192}, 4096)
        with self.assertRaises(InvalidOptions):
            validate_visual_budget(vl, {"resources.contextLength": 8192, "resources.slots": 2}, 4096)
        for config in ({"resources.contextLength": 2048}, {"resources.slots": 8}):
            with self.assertRaises(InvalidOptions):
                validate_visual_budget(vl, config, 4096)
        validate_visual_budget(vl, {"resources.maxOutputTokens": 13824, "resources.imageMaxTokens": 1}, 13824)
        with self.assertRaises(InvalidOptions):
            validate_visual_budget(vl, {"resources.maxOutputTokens": 13825, "resources.imageMaxTokens": 1}, 13825)

    def test_visual_budget_enforces_service_limit_without_affecting_pp(self):
        vl = "win32_PaddleOCRVL_1_6"
        validate_visual_budget(vl, {"resources.contextLength": 16384, "resources.maxOutputTokens": 8192}, 8192)
        with self.assertRaises(InvalidOptions):
            validate_visual_budget(vl, {"resources.contextLength": 16384, "resources.maxOutputTokens": 8192}, 8193)
        with self.assertRaises(InvalidOptions):
            validate_visual_budget(vl, {"resources.slots": 1}, 5000)
        # 无资源契约的后端不套用视觉预算，有契约的其他插件也遵守相同边界。
        validate_visual_budget("win32_PaddleOCRv6", {}, 65536)
        validate_visual_budget("future-visual-backend", {"resources.slots": 1}, 4096)
        with self.assertRaises(InvalidOptions):
            validate_visual_budget("future-visual-backend", {"resources.slots": 8}, 4096)

    def test_page_range_is_bounded_and_not_boolean(self):
        self.assertEqual(validate_page_range([1, 2]), [1, 2])
        for value in ([True, 2], [2, 1], [0, 2], [1, 10000], [1.0, 2], "1-2"):
            with self.assertRaises(InvalidOptions):
                validate_page_range(value)


if __name__ == "__main__":
    unittest.main()
