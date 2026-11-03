"""首页原生验收的纯判定契约：语言齐全不代表链接已在视口内。"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

SOURCE = Path(__file__).with_name("test_stored_native_ui.py")
spec = importlib.util.spec_from_file_location("stored_home_contract_driver", SOURCE)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
TARGET = "https://github.com/Dominic485649/UMI-OCR"


def fixture():
    return {"profile": "navigation", "scenario_completed": True, "normal_exit": True,
        "errors": [], "safety_blocks": [], "checks": {
            **{key: {"status": "PASS"} for key in driver.REQUIRED},
            "model_settings": {"status": "NOT_APPLICABLE"},
            "navigation_repository": {"status": "PASS", "languages": [
                {"code": code, "visible_link": {"fully_visible": True, "rendered_target": TARGET}}
                for code in driver.LANGUAGES]}}}


class HomepageAcceptance(unittest.TestCase):
    def test_navigation_requires_real_visible_links_not_model_settings(self):
        record = fixture()
        self.assertEqual(driver.acceptance(record)["status"], "PASS")
        record["profile"] = "base"
        self.assertEqual(driver.acceptance(record)["status"], "INCOMPLETE")

    def test_base_without_extra_home_check_keeps_original_contract(self):
        record = fixture()
        record["profile"] = "base"
        record["checks"]["model_settings"]["status"] = "PASS"
        del record["checks"]["navigation_repository"]
        self.assertEqual(driver.acceptance(record)["status"], "PASS")
        record["homepage_repository_required"] = True
        self.assertEqual(driver.acceptance(record)["status"], "INCOMPLETE")

    def test_missing_duplicate_or_unrun_language_fails(self):
        for change in ("missing", "duplicate", "not_run"):
            with self.subTest(change=change):
                record = fixture()
                home = record["checks"]["navigation_repository"]
                if change == "missing":
                    home["languages"].pop()
                elif change == "duplicate":
                    home["languages"][-1]["code"] = home["languages"][0]["code"]
                else:
                    home["status"] = "NOT_RUN"
                self.assertEqual(driver.acceptance(record)["status"], "INCOMPLETE")

    def test_text_exists_without_character_visibility_cannot_pass(self):
        for evidence in ({}, {"fully_visible": False, "rendered_target": TARGET},
                {"fully_visible": True, "rendered_target": "https://example.invalid/"}):
            with self.subTest(evidence=evidence):
                record = fixture()
                record["checks"]["navigation_repository"]["languages"][-1]["visible_link"] = copy.deepcopy(evidence)
                self.assertEqual(driver.acceptance(record)["status"], "INCOMPLETE")

    def test_early_exit_or_safety_block_cannot_pass(self):
        for field in ("scenario_completed", "normal_exit", "safety_blocks", "errors"):
            with self.subTest(field=field):
                record = fixture()
                record[field] = False if field in ("scenario_completed", "normal_exit") else ["fixture failure"]
                self.assertEqual(driver.acceptance(record)["status"], "INCOMPLETE")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = driver.plain(args.output)
    if not output.is_relative_to(driver.REPO / "build/audit") or not output.parent.is_dir() or output.exists():
        parser.error("只写入本项目既存审计根下的全新结果")
    before = sorted(name for name in sys.modules if name.startswith("PySide6"))
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HomepageAcceptance))
    after = sorted(name for name in sys.modules if name.startswith("PySide6"))
    record = {"status": "PASS" if result.wasSuccessful() and not result.skipped and not before and before == after else "FAIL",
        "testsRun": result.testsRun, "failures": [(str(case), value) for case, value in result.failures],
        "errors": [(str(case), value) for case, value in result.errors], "skipped": len(result.skipped),
        "driverSha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "testSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "qtLoaded": bool(after), "scope": "纯验收判定契约，不启动候选或模型；真实逐字锚点和滚轮另行原生验证。"}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: record[key] for key in ("status", "testsRun", "driverSha256")}, ensure_ascii=False))
    raise SystemExit(0 if record["status"] == "PASS" else 1)
