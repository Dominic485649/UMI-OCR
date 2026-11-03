"""实际 Mission/ManagedMission 源码回归；Qt 仅替换为标准库线程原语。

不加载模型、用户配置或安装目录，不创建 QApplication，也不启动 GPU。
"""
import importlib.util
import logging
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "UmiOCR-data"
sys.path.insert(0, str(DATA))
from py_src.mission.backend_runtime import RuntimeCoordinator


class Mutex:
    def __init__(self):
        self._lock = threading.Lock()

    def lock(self):
        self._lock.acquire()

    def unlock(self):
        self._lock.release()


class ThreadPool:
    def __init__(self):
        self.threads = []
        self._lock = threading.Lock()

    @classmethod
    def globalInstance(cls):
        return cls()

    def start(self, runnable):
        thread = threading.Thread(target=runnable.run, daemon=True)
        with self._lock:
            self.threads.append(thread)
            thread.start()

    def activeThreadCount(self):
        return sum(thread.is_alive() for thread in self.threads)

    def maxThreadCount(self):
        return 32

    def setMaxThreadCount(self, _count):
        pass

    def waitForDone(self, milliseconds):
        deadline = time.monotonic() + milliseconds / 1000
        while True:
            with self._lock:
                threads = tuple(self.threads)
            for thread in threads:
                thread.join(max(0, deadline - time.monotonic()))
            with self._lock:
                if all(not thread.is_alive() for thread in self.threads):
                    return True
            if time.monotonic() >= deadline:
                return False


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


qt = types.ModuleType("PySide6.QtCore")
qt.QMutex, qt.QRunnable, qt.QThreadPool = Mutex, object, ThreadPool
with patch.dict(sys.modules, {
    "PySide6": types.ModuleType("PySide6"),
    "PySide6.QtCore": qt,
    "umi_log": types.SimpleNamespace(logger=Mock(spec=logging.Logger)),
}):
    source_thread_pool = load_source(
        "py_src.utils.thread_pool", DATA / "py_src/utils/thread_pool.py")
    source_mission = load_source(
        "py_src.mission.mission", DATA / "py_src/mission/mission.py")
    source_managed = load_source(
        "py_src.mission.managed_mission", DATA / "py_src/mission/managed_mission.py")


class FakeApi:
    def __init__(self):
        self.cancelled = []
        self.current = None
        self.stopped = 0

    def start(self, _values):
        return ""

    def runPath(self, value):
        return {"code": 100, "data": value}

    def cancel(self):
        self.cancelled.append(self.current)

    def release(self):
        return "[Success]"

    def stop(self):
        self.stopped += 1


class ControlledMission(source_managed.ManagedMission):
    _capability = "ocr"

    def __init__(self, pool, api=None, global_manager=True):
        super().__init__(global_manager)
        self._schedulingMode = "1234"
        self._apiKey = "fake"
        self._api = pool.handle("ocr", "fake", {}, lambda *_: api or FakeApi())

    def _startMsns(self):
        # Tests explicitly drive the actual queue runner for reproducible order.
        pass

    def msnPreTask(self, info):
        return self._api.start(info.get("argd", {}))

    def msnTask(self, _info, item):
        return self._api.runPath(item["path"])


class ManagedMissionTests(unittest.TestCase):
    def setUp(self):
        self.pool = RuntimeCoordinator()
        self.patch = patch.object(source_managed, "BackendRuntime", self.pool)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.threads = []
        self.events = []

    def tearDown(self):
        for event in self.events:
            event.set()
        for thread in self.threads:
            thread.join(3)
            self.assertFalse(thread.is_alive(), "controlled worker did not finish")

    def event(self):
        result = threading.Event()
        self.events.append(result)
        return result

    def spawn(self, function):
        thread = threading.Thread(target=function, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def add(self, mission, value="item", **info):
        return mission.addMissionList(info, [{"path": value}])

    def test_new_http_manager_obeys_global_pending_switch(self):
        self.pool.defer_admissions(True)
        mission = ControlledMission(self.pool, global_manager=False)
        ident = self.add(mission, "new-http")
        self.assertFalse(ident.startswith("[Error]"))
        self.assertEqual(mission.getMissionListsLength(), {})
        self.assertEqual(self.pool.status()["pendingTasks"], 0)
        self.assertIn(ident, mission._deferredMissions)
        self.pool.defer_admissions(False)
        self.assertEqual(self.pool.status()["pendingTasks"], 1)
        mission._taskRun()
        self.assertFalse(self.pool.busy())

    def test_reserve_defer_and_enqueue_share_admission_lock(self):
        mission = ControlledMission(self.pool)
        reserved, proceed, changing, changed = [self.event() for _ in range(4)]
        original = self.pool.reserve

        def reserve(key, owner):
            original(key, owner)
            reserved.set()
            self.assertTrue(proceed.wait(3))

        self.pool.reserve = reserve
        self.spawn(lambda: self.add(mission))
        self.assertTrue(reserved.wait(2))

        def change():
            changing.set()
            mission.deferAdmissions(True)
            changed.set()

        self.spawn(change)
        self.assertTrue(changing.wait(2))
        self.assertFalse(changed.wait(0.05), "defer overtook a half-admitted reservation")
        proceed.set()
        self.assertTrue(changed.wait(2))
        self.assertEqual(len(mission.getMissionListsLength()), 1)
        self.assertFalse(mission._deferredMissions)
        mission._taskRun()
        self.assertFalse(self.pool.busy())

    def test_deferred_tasks_do_not_reserve_until_resume(self):
        mission = ControlledMission(self.pool)
        mission.deferAdmissions(True)
        ident = self.add(mission)
        self.assertFalse(self.pool.busy())
        self.assertIn(ident, mission._deferredMissions)
        mission.deferAdmissions(False)
        self.assertEqual(self.pool.status()["pendingTasks"], 1)
        mission._taskRun()
        self.assertFalse(self.pool.busy())

    def test_deferred_overflow_notifies_every_returned_id(self):
        mission = ControlledMission(self.pool)
        mission.deferAdmissions(True)
        ended = []
        ids = [self.add(mission, str(index), onEnd=lambda info, msg:
                        ended.append((info["msnID"], msg))) for index in range(65)]
        self.assertTrue(all(not ident.startswith("[Error]") for ident in ids))
        mission.deferAdmissions(False)
        self.assertEqual(ended[0][0], ids[-1])
        self.assertTrue(ended[0][1].startswith("[Error]"))
        self.assertFalse(mission._deferredMissions)
        self.assertEqual(len(mission.getMissionListsLength()), 64)
        mission._taskRun()
        self.assertEqual(len(ended), 65)
        self.assertEqual({ident for ident, _ in ended}, set(ids))
        self.assertFalse(self.pool.busy())

    def test_deferred_admission_exception_ends_id_and_continues(self):
        mission = ControlledMission(self.pool)
        mission.deferAdmissions(True)
        ended = []
        first = self.add(mission, "bad", onEnd=lambda info, msg:
                         ended.append((info["msnID"], msg)))
        second = self.add(mission, "good", onEnd=lambda info, msg:
                          ended.append((info["msnID"], msg)))
        reserve = self.pool.reserve

        def fail_once(key, owner):
            if key == first:
                raise RuntimeError("forced admission failure")
            reserve(key, owner)

        self.pool.reserve = fail_once
        mission.deferAdmissions(False)
        self.assertEqual(ended[0][0], first)
        self.assertTrue(ended[0][1].startswith("[Error]"))
        self.assertIn(second, mission.getMissionListsLength())
        mission._taskRun()
        self.assertEqual(len(ended), 2)
        self.assertFalse(self.pool.busy())

    def test_resume_keeps_deferred_fifo_ahead_of_new_admission(self):
        mission = ControlledMission(self.pool)
        mission.deferAdmissions(True)
        first = self.add(mission, "first")
        second = self.add(mission, "second")
        reserved, proceed, submitted = [self.event() for _ in range(3)]
        reserve = self.pool.reserve

        def pause_first(key, owner):
            reserve(key, owner)
            if key == first:
                reserved.set()
                self.assertTrue(proceed.wait(3))

        self.pool.reserve = pause_first
        self.spawn(lambda: mission.deferAdmissions(False))
        self.assertTrue(reserved.wait(2))
        ids = []
        self.spawn(lambda: (ids.append(self.add(mission, "third")), submitted.set()))
        self.assertFalse(submitted.wait(0.05))
        proceed.set()
        self.assertTrue(submitted.wait(2))
        self.assertEqual(list(mission.getMissionListsLength()), [first, second, ids[0]])
        mission._taskRun()
        self.assertFalse(self.pool.busy())

    def test_cancel_marks_stop_before_backend_returns_and_holds_gate(self):
        started, finish_work, cancel_started, finish_cancel, other_entered = [
            self.event() for _ in range(5)]
        case = self

        class Api(FakeApi):
            def runPath(self, value):
                started.set()
                case.assertTrue(finish_work.wait(3))
                return {"code": 100, "data": value}

            def cancel(self):
                cancel_started.set()
                finish_work.set()
                case.assertTrue(finish_cancel.wait(3))

        mission = ControlledMission(self.pool, Api())
        messages, delivered = [], []
        ident = self.add(mission, onEnd=lambda _i, msg: messages.append(msg),
                         onGet=lambda *args: delivered.append(args))
        worker = self.spawn(mission._taskRun)
        self.assertTrue(started.wait(2))
        stopper = self.spawn(lambda: mission.stopMissionList(ident))
        self.assertTrue(cancel_started.wait(2))
        self.assertEqual(mission._msnInfoDict[ident]["state"], "stop")

        def other():
            with self.pool.operation("other"):
                other_entered.set()

        self.spawn(other)
        self.assertFalse(other_entered.wait(0.05))
        finish_cancel.set()
        stopper.join(2)
        worker.join(2)
        self.assertTrue(other_entered.wait(2))
        self.assertEqual(messages, ["[Warning] Task stop."])
        self.assertFalse(delivered)

    def test_stale_cancel_token_cannot_cancel_next_queue(self):
        first_started, release_first, second_started, release_second = [
            self.event() for _ in range(4)]
        before_cancel, proceed_cancel = self.event(), self.event()
        case = self

        class Api(FakeApi):
            def runPath(self, value):
                self.current = value
                if value == "A":
                    first_started.set()
                    case.assertTrue(release_first.wait(3))
                else:
                    second_started.set()
                    case.assertTrue(release_second.wait(3))
                self.current = None
                return {"code": 100, "data": value}

            def cancel(self):
                super().cancel()
                release_second.set()

        api = Api()
        mission = ControlledMission(self.pool, api)
        messages = []
        first = self.add(mission, "A", onEnd=lambda _i, msg: messages.append(("A", msg)))
        self.add(mission, "B", onEnd=lambda _i, msg: messages.append(("B", msg)))
        cancel = mission._api.cancel

        def delay_cancel(token=None):
            before_cancel.set()
            self.assertTrue(proceed_cancel.wait(3))
            cancel(token)

        mission._api.cancel = delay_cancel
        worker = self.spawn(mission._taskRun)
        self.assertTrue(first_started.wait(2))
        stopper = self.spawn(lambda: mission.stopMissionList(first))
        self.assertTrue(before_cancel.wait(2))
        release_first.set()
        self.assertTrue(second_started.wait(2))
        proceed_cancel.set()
        stopper.join(2)
        self.assertFalse(stopper.is_alive())
        self.assertFalse(api.cancelled)
        self.assertFalse(release_second.is_set())
        release_second.set()
        worker.join(2)
        self.assertEqual(messages, [("A", "[Warning] Task stop."), ("B", "[Success]")])

    def test_cancel_exception_does_not_lose_stop_or_end_notification(self):
        started, finish = self.event(), self.event()
        case = self

        class Api(FakeApi):
            def runPath(self, value):
                started.set()
                case.assertTrue(finish.wait(3))
                return {"code": 100, "data": value}

            def cancel(self):
                finish.set()
                raise RuntimeError("forced cancel failure")

        mission = ControlledMission(self.pool, Api())
        messages = []
        ident = self.add(mission, onEnd=lambda _i, msg: messages.append(msg))
        worker = self.spawn(mission._taskRun)
        self.assertTrue(started.wait(2))
        mission.stopMissionList(ident)
        worker.join(2)
        self.assertEqual(messages, ["[Warning] Task stop."])
        self.assertTrue(mission._api._cancel_finished.is_set())
        self.assertFalse(self.pool.busy())

    def test_stop_all_marks_every_queue_before_backend_cancel(self):
        started, finish = self.event(), self.event()
        observed, messages = [], []
        case = self

        class Api(FakeApi):
            def runPath(self, value):
                started.set()
                case.assertTrue(finish.wait(3))
                return {"code": 100, "data": value}

            def cancel(self):
                observed.append([info["state"] for info in mission._msnInfoDict.values()])
                finish.set()

        mission = ControlledMission(self.pool, Api())
        self.add(mission, "active", onEnd=lambda _i, msg: messages.append(msg))
        self.add(mission, "queued", onEnd=lambda _i, msg: messages.append(msg))
        worker = self.spawn(mission._taskRun)
        self.assertTrue(started.wait(2))
        mission.stopAllMissions()
        worker.join(2)
        self.assertEqual(observed, [["stop", "stop"]])
        self.assertEqual(messages, ["[Warning] Task stop."] * 2)
        self.assertFalse(self.pool.busy())

    def test_waiting_mission_cancel_does_not_touch_other_handle(self):
        started, release, ended = self.event(), self.event(), self.event()
        case = self

        class Api(FakeApi):
            def runPath(self, value):
                started.set()
                case.assertTrue(release.wait(3))
                return {"code": 100, "data": value}

        api = Api()
        active = ControlledMission(self.pool, api, global_manager=False)
        waiting = ControlledMission(self.pool, api, global_manager=False)
        self.add(active)
        worker = self.spawn(active._taskRun)
        self.assertTrue(started.wait(2))
        ident = self.add(waiting, onEnd=lambda *_: ended.set())
        self.spawn(waiting._taskRun)
        with self.pool._condition:
            self.pool._condition.wait_for(lambda: bool(self.pool._queue), timeout=0.2)
        waiting.stopMissionList(ident)
        self.assertTrue(ended.wait(2))
        self.assertFalse(api.cancelled)
        self.assertEqual(api.stopped, 0)
        release.set()
        worker.join(2)
        self.assertFalse(self.pool.busy())

    def test_end_callback_sees_idle_and_can_reenter_at_capacity(self):
        self.pool._max_waiters = 1
        mission = ControlledMission(self.pool)
        observations, messages = [], []

        def on_end(_info, message):
            self.assertFalse(self.pool.busy(), "结束回调不占用模型执行许可或队列容量")
            with self.assertRaises(source_managed.BackendBusy):
                with self.pool.reconfiguration():
                    self.fail("结束回调完成前不能切换配置")
            observations.append((mission.getMissionListsLength(), mission.backendsBusy(),
                                 mission._api.release()))
            messages.append(message)
            ident = self.add(mission, "reentered", onEnd=lambda _i, msg: messages.append(msg))
            self.assertFalse(ident.startswith("[Error]"))

        self.add(mission, onEnd=on_end)
        mission._taskRun()
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0][:2], ({}, True))
        self.assertTrue(observations[0][2].startswith("[Success]"))
        self.assertEqual(messages, ["[Success]", "[Success]"])
        self.assertFalse(self.pool.busy())

    def test_reentrant_stop_from_callbacks_does_not_start_inference(self):
        for callback in ("onStart", "onReady"):
            with self.subTest(callback=callback):
                api = FakeApi()
                api.runPath = Mock(side_effect=AssertionError("cancelled task ran inference"))
                mission = ControlledMission(self.pool, api)
                messages = []
                info = {
                    callback: lambda info, *_: mission.stopMissionList(info["msnID"]),
                    "onEnd": lambda _info, msg: messages.append(msg),
                }
                self.add(mission, **info)
                mission._taskRun()
                api.runPath.assert_not_called()
                self.assertEqual(messages, ["[Warning] Task stop."])
                self.assertFalse(self.pool.busy())
                mission._api.stop()

    def test_private_completion_finally_stops_real_instance(self):
        api = FakeApi()
        mission = ControlledMission(self.pool, api, global_manager=False)
        self.add(mission)
        mission._taskRun()
        self.assertEqual(api.stopped, 1)
        self.assertIsNone(self.pool._entries[("ocr", "fake")].instance)
        self.assertFalse(self.pool.busy())

    def test_existing_mission_runtime_regressions_against_actual_source(self):
        # Reuse all existing non-GPU checks without configure_runtime(), DLL
        # mounting, QResource registration, or access to an installed package.
        name = "managed_source_mission_regressions"
        with patch.dict(sys.modules):
            regressions = load_source(name, ROOT / "tests/test_mission_runtime.py")
        regressions.Mission = source_mission.Mission
        regressions.thread_pool = source_thread_pool
        for function in (
            regressions.test_immediate_wait_has_no_lost_wakeup,
            regressions.test_stop_finishes_waiting_queue,
            regressions.test_full_qt_pool_does_not_expand,
            regressions.test_admission_during_worker_finish_is_not_stranded,
            regressions.test_worker_exception_finishes_queue_and_recovers,
            regressions.test_end_callback_can_reenter_and_switch_configuration,
            regressions.test_configuration_barrier_and_cancel,
        ):
            with self.subTest(function=function.__name__):
                function()
        self.assertTrue(source_thread_pool.GlobalThreadPool.waitForDone(5000))


if __name__ == "__main__":
    unittest.main()
