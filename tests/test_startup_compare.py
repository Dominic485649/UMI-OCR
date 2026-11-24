"""启动对照统计的纯逻辑验证，不启动EXE、Qt或模型。"""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("startup_compare", ROOT / "benchmarks/benchmark_startup_compare.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StartupCompareTests(unittest.TestCase):
    def test_consistent_difference_is_reproducible(self):
        pairs = [{"baselineMs": 1000 + i, "candidateMs": 900 + i} for i in range(8)]
        first = module.statistics_for(pairs)
        self.assertEqual(first, module.statistics_for(pairs))
        self.assertEqual(first["assessment"], "OBSERVED_IMPROVEMENT")
        self.assertEqual(first["pairedMedianBootstrap95PercentMs"], [100, 100])

    def test_fluctuation_does_not_claim_speedup(self):
        pairs = [{"baselineMs": 1000, "candidateMs": 1000 + i} for i in (-80, 40, -10, 60, 10, -40, -30, 80)]
        self.assertEqual(module.statistics_for(pairs)["assessment"], "INCONCLUSIVE")

    def test_regression_remains_regression(self):
        pairs = [{"baselineMs": 1000, "candidateMs": 1050 + i} for i in range(8)]
        self.assertEqual(module.statistics_for(pairs)["assessment"], "OBSERVED_REGRESSION")


if __name__ == "__main__":
    unittest.main(verbosity=2)
