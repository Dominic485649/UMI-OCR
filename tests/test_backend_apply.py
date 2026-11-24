"""配置串行应用／清理竞态的确定性回归，不启动模型。"""
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "UmiOCR-data"))
from py_src.mission.backend_apply import apply_backends
from py_src.mission.backend_runtime import BackendBusy, RuntimeCoordinator


class BackendApplyTests(unittest.TestCase):
    def setUp(self):
        self.runtime = RuntimeCoordinator()
        self.request = {"revision": 5, "interfaces": {
            "ocr": {"apiKey": "vl", "info": {}}, "document": {"apiKey": "vl", "info": {}}}}

    def test_serial_apply_allows_own_cleanup_and_blocks_other_operations(self):
        calls = []
        def configure(key, values):
            self.assertFalse(self.runtime.busy())
            with self.runtime.operation("old", idle_only=True, activate=False):
                calls.append(key)
            other = []
            def attempt():
                try:
                    with self.runtime.operation("other"):
                        other.append("错误地获得了许可")
                except BackendBusy:
                    other.append("busy")
            thread = threading.Thread(target=attempt)
            thread.start()
            thread.join(2)
            self.assertEqual(other, ["busy"])
            return "[Success]"
        managers = {key: Mock(setApi=Mock(side_effect=configure)) for key in ("ocr", "document")}
        result = apply_backends(self.runtime, managers, self.request)
        self.assertEqual(result["state"], "applied")
        self.assertEqual(calls, ["vl", "vl"])
        self.assertFalse(self.runtime.busy())

    def test_reservations_are_deferred_not_reported_as_failure(self):
        self.runtime.reserve("current", "pp")
        managers = {key: Mock() for key in ("ocr", "document")}
        result = apply_backends(self.runtime, managers, self.request)
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["applied"], {})
        self.assertFalse(managers["ocr"].setApi.called)
        self.runtime.unreserve("current")
        managers["ocr"].setApi.return_value = "[Success]"
        managers["document"].setApi.return_value = "[Success]"
        self.assertEqual(apply_backends(self.runtime, managers, self.request)["state"], "applied")

    def test_real_failure_preserves_successful_subset(self):
        managers = {"ocr": Mock(), "document": Mock()}
        managers["ocr"].setApi.return_value = "[Success]"
        managers["document"].setApi.return_value = "[Error] invalid backend"
        result = apply_backends(self.runtime, managers, self.request)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(set(result["applied"]), {"ocr"})
        self.assertFalse(self.runtime.busy())

    def test_idle_notification_and_global_admission_barrier(self):
        notifications = []
        class Subscriber:
            def changed(self):
                notifications.append(True)
        subscriber = Subscriber()
        self.runtime.subscribe(subscriber.changed)
        manager = Mock()
        self.runtime.register_manager(manager)
        self.runtime.defer_admissions(True)
        self.assertTrue(self.runtime.admissions_deferred())
        manager.deferAdmissions.assert_called_with(True)
        self.runtime.reserve("last", "pp")
        self.runtime.unreserve("last")
        self.assertTrue(notifications)
        self.runtime.defer_admissions(False)
        self.assertFalse(self.runtime.admissions_deferred())
        manager.deferAdmissions.assert_called_with(False)


if __name__ == "__main__":
    unittest.main()
