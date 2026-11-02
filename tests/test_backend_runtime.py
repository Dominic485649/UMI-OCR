"""无需推理依赖的共享执行许可与后端去重回归。"""
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "UmiOCR-data"))
from py_src.mission.backend_runtime import RuntimeCoordinator, BackendBusy, BackendCancelled


class FakeApi:
    def __init__(self, owner, config, events):
        self.owner, self.config, self.events = owner, config, events
        self.loaded = False
        self.events.append((owner, "create"))

    def start(self, values):
        self.loaded = True
        self.events.append((self.owner, "start"))
        return ""

    def release(self):
        self.loaded = False
        self.events.append((self.owner, "release"))
        return "[Success]"

    def stop(self):
        self.release()

    def get_status(self):
        return {"state": "loaded" if self.loaded else "unloaded"}

    def runPath(self, value):
        assert self.loaded
        return {"code": 100, "value": value}


class BackendRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = RuntimeCoordinator()
        self.events = []
        self.factory = lambda owner, config: FakeApi(owner, config, self.events)

    def handle(self, owner="cuda", config=None):
        return self.runtime.handle("ocr", owner, config or {}, self.factory)

    def test_same_backend_has_one_real_instance(self):
        first, second = self.handle(), self.handle()
        with first.context():
            first.start({"longSide": 4000})
            first.runPath("a")
        with second.context():
            second.start({"longSide": 4000})
            second.runPath("b")
        self.assertEqual(self.events.count(("cuda", "create")), 1)

    def test_switch_releases_previous_owner(self):
        first, second = self.handle(), self.handle("vl")
        first.start({})
        second.start({})
        self.assertLess(self.events.index(("cuda", "release")), self.events.index(("vl", "create")))
        first.runPath("reload")
        self.assertGreater(self.events.count(("cuda", "start")), 1)

    def test_reserved_work_prevents_idle_cleanup(self):
        handle = self.handle()
        handle.start({})
        self.runtime.reserve("pending", "cuda")
        self.assertTrue(handle.release().startswith("[Error]"))
        self.runtime.unreserve("pending")
        self.assertTrue(handle.release().startswith("[Success]"))

    def test_waiting_cancellation_does_not_steal_execution(self):
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def active():
            with self.runtime.operation("cuda"):
                entered.set()
                release.wait(2)
        def waiting():
            try:
                with self.runtime.operation("vl", cancelled.is_set):
                    errors.append("取消后不应取得许可")
            except BackendCancelled:
                pass
        first = threading.Thread(target=active)
        second = threading.Thread(target=waiting)
        first.start()
        self.assertTrue(entered.wait(1))
        second.start()
        cancelled.set()
        second.join(1)
        release.set()
        first.join(1)
        self.assertFalse(second.is_alive())
        self.assertFalse(errors)
        self.assertFalse(self.runtime.busy())

    def test_failed_factory_does_not_leak_gate(self):
        bad = self.runtime.handle("ocr", "bad", {}, lambda *_: "[Error] 模拟失败")
        with self.assertRaises(RuntimeError):
            bad.start({})
        self.assertFalse(self.runtime.busy())
        self.handle().start({})

    def test_reset_is_blocked_by_reservation(self):
        self.runtime.reserve("job", "cuda")
        with self.assertRaises(BackendBusy):
            self.runtime.reset()
        self.runtime.unreserve("job")
        self.runtime.reset()

    def test_cancel_must_finish_before_execution_permit_is_released(self):
        started, finish_work = threading.Event(), threading.Event()
        cancel_started, finish_cancel = threading.Event(), threading.Event()
        other_entered = threading.Event()
        class CancelApi(FakeApi):
            def cancel(self):
                cancel_started.set()
                finish_cancel.wait(2)
        handle = self.runtime.handle("ocr", "cuda", {},
            lambda owner, config: CancelApi(owner, config, self.events))
        def work():
            with handle.context():
                handle.start({})
                started.set()
                finish_work.wait(2)
        def other():
            with self.runtime.operation("vl"):
                other_entered.set()
        worker = threading.Thread(target=work)
        worker.start()
        self.assertTrue(started.wait(1))
        cancelling = threading.Thread(target=handle.cancel)
        cancelling.start()
        self.assertTrue(cancel_started.wait(1))
        waiting = threading.Thread(target=other)
        waiting.start()
        finish_work.set()
        self.assertFalse(other_entered.wait(0.05))
        finish_cancel.set()
        for thread in (worker, cancelling, waiting):
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertTrue(other_entered.is_set())

    def test_concurrent_workers_are_serialized(self):
        active = 0
        peak = 0
        lock = threading.Lock()
        barrier = threading.Barrier(5)
        def work(index):
            nonlocal active, peak
            barrier.wait()
            with self.runtime.operation(str(index)):
                with lock:
                    active += 1
                    peak = max(peak, active)
                threading.Event().wait(0.015)
                with lock:
                    active -= 1
        workers = [threading.Thread(target=work, args=(index,)) for index in range(5)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)
        self.assertEqual(peak, 1)
        self.assertFalse(self.runtime.busy())

    def test_last_handle_stop_runs_final_stop_once(self):
        class FinalApi(FakeApi):
            def stop(api):
                self.events.append((api.owner, "stop"))
                super().stop()

        first = self.runtime.handle("document", "vl", {},
            lambda owner, config: FinalApi(owner, config, self.events))
        second = self.runtime.handle("document", "vl", {}, self.factory)
        first.start({})
        first.stop()
        self.assertNotIn(("vl", "stop"), self.events)
        second.stop()
        second.stop()
        self.assertEqual(self.events.count(("vl", "stop")), 1)
        self.assertIsNone(self.runtime._entries[("document", "vl")].instance)
        self.assertFalse(self.runtime.busy())

    def test_stop_waits_for_all_reservations(self):
        class FinalApi(FakeApi):
            def stop(api):
                self.events.append((api.owner, "stop"))
                super().stop()

        handle = self.runtime.handle("ocr", "cuda", {},
            lambda owner, config: FinalApi(owner, config, self.events))
        handle.start({})
        self.runtime.reserve("accepted", "cuda")
        handle.stop()
        self.assertNotIn(("cuda", "stop"), self.events)
        self.runtime.unreserve("accepted")
        self.assertEqual(self.events.count(("cuda", "stop")), 1)
        self.assertFalse(self.runtime.busy())

    def test_stop_during_execution_waits_for_permit_exit(self):
        started, finish = threading.Event(), threading.Event()

        class FinalApi(FakeApi):
            def stop(api):
                self.events.append((api.owner, "stop"))
                super().stop()

        handle = self.runtime.handle("ocr", "cuda", {},
            lambda owner, config: FinalApi(owner, config, self.events))

        def work():
            with handle.context():
                handle.start({})
                started.set()
                finish.wait(3)

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        try:
            self.assertTrue(started.wait(2))
            handle.stop()
            self.assertNotIn(("cuda", "stop"), self.events)
        finally:
            finish.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.events.count(("cuda", "stop")), 1)
        self.assertFalse(self.runtime.busy())

    def test_other_capability_handle_preserves_shared_owner(self):
        class FinalApi(FakeApi):
            def stop(api):
                self.events.append((api.owner, "stop"))
                super().stop()

        factory = lambda owner, config: FinalApi(owner, config, self.events)
        ocr = self.runtime.handle("ocr", "vl", {}, factory)
        document = self.runtime.handle("document", "vl", {}, factory)
        ocr.start({})
        document.start({})
        document.stop()
        self.assertNotIn(("vl", "stop"), self.events)
        ocr.runPath("still usable")
        ocr.stop()
        self.assertEqual(self.events.count(("vl", "stop")), 2)

    def test_final_cleanup_preserves_active_service_lease_and_other_owner(self):
        owned, foreign = Mock(), Mock()
        services = types.ModuleType("py_src.plugins_controller.services")
        services.PluginServices = types.SimpleNamespace(_entries={
            ("cuda", "model"): {"instance": owned},
            ("other", "model"): {"instance": foreign},
        })
        handle = self.handle()
        handle.start({})
        self.runtime.reserve("leased-task", "cuda")
        with patch.dict(sys.modules, {services.__name__: services}):
            handle.stop()
            owned.stop_owned.assert_not_called()
            foreign.stop_owned.assert_not_called()
            self.runtime.unreserve("leased-task")
            owned.stop_owned.assert_called_once_with()
            foreign.stop_owned.assert_not_called()
        self.assertFalse(self.runtime.busy())

    def test_nested_start_does_not_replace_task_cancel_token(self):
        cancelled = []

        class CancelApi(FakeApi):
            def cancel(api):
                cancelled.append("cancel")

        handle = self.runtime.handle("ocr", "cuda", {},
            lambda owner, config: CancelApi(owner, config, self.events))
        old, current = object(), object()
        with handle.context(token=old):
            handle.start({})
        with handle.context(token=current):
            handle.start({})
            handle.cancel(old)
            self.assertFalse(cancelled)
            handle.cancel(current)
            self.assertEqual(cancelled, ["cancel"])
        self.assertFalse(self.runtime.busy())

    def test_final_stop_exception_releases_gate_and_retains_instance(self):
        class FailingStop(FakeApi):
            def stop(api):
                raise RuntimeError("forced final stop failure")

        handle = self.runtime.handle("document", "vl", {},
            lambda owner, config: FailingStop(owner, config, self.events))
        handle.start({})
        instance = self.runtime._entries[("document", "vl")].instance
        with self.assertRaisesRegex(RuntimeError, "forced final stop failure"):
            handle.stop()
        self.assertFalse(self.runtime.busy())
        self.assertIs(self.runtime._entries[("document", "vl")].instance, instance)
        other = self.handle()
        other.start({})
        self.assertFalse(self.runtime.busy())

    def test_final_stop_does_not_hold_registration_mutex(self):
        stopping, finish_stop, registered = [threading.Event() for _ in range(3)]

        class FinalApi(FakeApi):
            def stop(api):
                stopping.set()
                finish_stop.wait(3)
                super().stop()

        handle = self.runtime.handle("ocr", "cuda", {},
            lambda owner, config: FinalApi(owner, config, self.events))
        handle.start({})
        closer = threading.Thread(target=handle.stop, daemon=True)
        replacements = []

        def register():
            replacements.append(self.handle())
            registered.set()

        closer.start()
        registrant = threading.Thread(target=register, daemon=True)
        try:
            self.assertTrue(stopping.wait(2))
            registrant.start()
            self.assertTrue(registered.wait(1), "plugin stop held the registry/admission mutex")
        finally:
            finish_stop.set()
            closer.join(3)
            if registrant.ident is not None:
                registrant.join(3)
        self.assertFalse(closer.is_alive())
        self.assertTrue(replacements)
        replacements[0].start({})
        replacements[0].runPath("new task after cleanup")
        self.assertFalse(self.runtime.busy())

    def test_waiting_execution_order_stays_fifo(self):
        entered, finish = threading.Event(), threading.Event()
        order, workers = [], []

        def first():
            with self.runtime.operation("initial"):
                entered.set()
                finish.wait(3)

        first_worker = threading.Thread(target=first, daemon=True)
        first_worker.start()
        self.assertTrue(entered.wait(2))
        try:
            for index in range(3):
                queued = threading.Event()

                def waiting(index=index, queued=queued):
                    def not_cancelled():
                        queued.set()
                        return False
                    with self.runtime.operation(str(index), not_cancelled):
                        order.append(index)

                worker = threading.Thread(target=waiting, daemon=True)
                workers.append(worker)
                worker.start()
                self.assertTrue(queued.wait(2))
        finally:
            finish.set()
            first_worker.join(3)
            for worker in workers:
                worker.join(3)
        self.assertEqual(order, [0, 1, 2])
        self.assertFalse(self.runtime.busy())


if __name__ == "__main__":
    unittest.main()
