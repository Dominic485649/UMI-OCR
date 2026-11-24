"""热配置验收调度器的无 GUI 回归，不运行应用或改配置。"""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hot_ui_scheduler_test", ROOT / "tests/test_hot_ui.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SchedulerTests(unittest.TestCase):
    def test_steps_return_to_scheduler_between_actions(self):
        queue, actions, completed, failures = [], [], [], []
        def scenario():
            actions.append("first")
            yield 10
            actions.append("second")
            yield 300
            actions.append("third")
        module.start_steps(scenario(), lambda delay, callback: queue.append((delay, callback)), lambda: completed.append(True), failures.append)
        self.assertEqual(actions, [])
        delay, callback = queue.pop(0)
        self.assertEqual(delay, 0)
        callback()
        self.assertEqual(actions, ["first"])
        delay, callback = queue.pop(0)
        self.assertEqual(delay, 10)
        callback()
        self.assertEqual(actions, ["first", "second"])
        delay, callback = queue.pop(0)
        self.assertEqual(delay, 300)
        callback()
        self.assertEqual(completed, [True])
        self.assertEqual(failures, [])
        self.assertEqual(queue, [])

    def test_wait_preserves_timeout_and_does_not_busy_pump(self):
        ticks = iter([0, 1, 12])
        waiting = module.wait_transition(lambda: False, timeout=12, label="Initial apply", clock=lambda: next(ticks))
        self.assertEqual(next(waiting), 10)
        with self.assertRaisesRegex(AssertionError, "Initial apply timed out"):
            next(waiting)

    def test_satisfied_wait_returns_without_a_timer(self):
        waiting = module.wait_transition(lambda: True, clock=lambda: 0)
        with self.assertRaises(StopIteration):
            next(waiting)

    def test_failed_step_cannot_continue_or_complete(self):
        queue, completed, failures = [], [], []
        def scenario():
            yield 10
            raise AssertionError("original assertion")
        module.start_steps(scenario(), lambda delay, callback: queue.append(callback), lambda: completed.append(True), failures.append)
        queue.pop(0)()
        queue.pop(0)()
        self.assertEqual(completed, [])
        self.assertEqual(queue, [])
        self.assertIsInstance(failures[0], AssertionError)

    def test_early_normal_exit_after_first_frame_is_not_acceptance(self):
        for hot in (False, True):
            with self.subTest(hot=hot):
                report = {"interactive_seconds": 1.0, "normal_exit": True,
                          "hot": hot, "scenario_completed": False, "errors": []}
                errors = module.completion_errors(report, hot_required=True)
                self.assertTrue(errors)
                self.assertIn("未完成", errors[0])
        self.assertEqual(module.completion_errors({"scenario_completed": True, "hot": True}, True), [])
        self.assertTrue(module.completion_errors({"scenario_completed": True, "hot": False}, True))

    def test_invalid_delay_is_failure(self):
        queue, failures = [], []
        module.start_steps(iter([-1]), lambda delay, callback: queue.append(callback), lambda: self.fail("must not complete"), failures.append)
        queue.pop(0)()
        self.assertIsInstance(failures[0], ValueError)
        self.assertEqual(queue, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
