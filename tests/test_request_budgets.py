"""并发临时空间预算不会超售，释放可复用。"""
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "UmiOCR-data"))
from py_src.server.request_budgets import ByteBudget


class RequestBudgetTests(unittest.TestCase):
    def test_oversubscription_is_rejected_and_release_reused(self):
        budget = ByteBudget(10)
        budget.take(8)
        with self.assertRaises(ValueError):
            budget.take(3)
        self.assertEqual(budget.used, 8)
        budget.release(8)
        budget.take(10)
        self.assertEqual(budget.used, 10)

    def test_concurrent_reservations_are_atomic(self):
        budget = ByteBudget(5)
        accepted = []
        barrier = threading.Barrier(10)
        def reserve():
            barrier.wait()
            try:
                budget.take(1)
                accepted.append(True)
            except ValueError:
                pass
        threads = [threading.Thread(target=reserve) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(accepted), 5)
        self.assertEqual(budget.used, 5)


if __name__ == "__main__":
    unittest.main()
