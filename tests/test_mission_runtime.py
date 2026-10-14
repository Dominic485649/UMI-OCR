"""Small regression checks for mission wait and thread-pool scheduling."""

import argparse
import threading
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime

Mission = None
thread_pool = None


def test_immediate_wait_has_no_lost_wakeup():
    """The worker may finish before the caller starts waiting."""
    class ImmediateMission(Mission):
        def msnTask(self, _info, msn):
            return {"code": 100, "data": msn["value"]}

    mission = ImmediateMission()
    result = mission.addMissionWait({}, [{"value": "ok"}])
    assert result[0]["result"]["data"] == "ok"


def test_stop_finishes_waiting_queue():
    class StoppableMission(Mission):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def msnTask(self, _info, _msn):
            self.started.set()
            self.release.wait(2)
            return {"code": 100, "data": "released"}

    mission = StoppableMission()
    ended = threading.Event()
    messages = []

    mission_id = mission.addMissionList(
        {
            "argd": {},
            "onEnd": lambda _info, message: (messages.append(message), ended.set()),
        },
        [{"value": "never"}],
    )
    assert not mission_id.startswith("[Error]")
    assert mission.started.wait(2)
    mission.stopMissionList(mission_id)
    mission.release.set()
    assert ended.wait(2)
    assert messages == ["[Warning] Task stop."]


def test_full_qt_pool_does_not_expand():
    runnable = object()
    with patch.object(thread_pool.GlobalThreadPool, "activeThreadCount", return_value=1), patch.object(
        thread_pool.GlobalThreadPool, "maxThreadCount", return_value=1
    ), patch.object(thread_pool.GlobalThreadPool, "setMaxThreadCount") as set_max, patch.object(
        thread_pool.GlobalThreadPool, "start"
    ) as start:
        thread_pool.threadPoolStart(runnable)
    set_max.assert_not_called()
    start.assert_called_once_with(runnable)


def test_admission_during_worker_finish_is_not_stranded():
    """An admission after the worker sees an empty queue still needs a worker."""
    class FinishPausedMission(Mission):
        def __init__(self):
            super().__init__()
            self.finishing = threading.Event()
            self.release_finish = threading.Event()
            self.pause_once = True

        def msnTask(self, _info, item):
            return {"code": 100, "data": item["value"]}

        def _taskFinish(self):
            if self.pause_once:
                self.pause_once = False
                self.finishing.set()
                assert self.release_finish.wait(5), "finish barrier timed out"
            super()._taskFinish()

    mission = FinishPausedMission()
    completed = threading.Event()
    mission.addMissionList({}, [{"value": "first"}])
    assert mission.finishing.wait(2), "worker did not reach its finish boundary"
    try:
        mission.addMissionList(
            {"onEnd": lambda *_args: completed.set()}, [{"value": "second"}]
        )
    finally:
        mission.release_finish.set()
    assert completed.wait(2), "mission admitted during worker finish was stranded"


def test_worker_exception_finishes_queue_and_recovers():
    """A failing plugin or callback must not leave the task slot occupied."""
    class FailingMission(Mission):
        def msnPreTask(self, info):
            if info["argd"].get("phase") == "pre":
                raise RuntimeError("forced preparation failure")
            return ""

        def msnTask(self, info, item):
            if info["argd"].get("phase") == "run":
                raise RuntimeError("forced inference failure")
            return {"code": 100, "data": item["value"]}

    def fail_callback(*_args):
        raise RuntimeError("forced callback failure")

    for phase in ("pre", "run", "callback"):
        mission = FailingMission()
        failed = threading.Event()
        recovered = threading.Event()
        messages = []
        mission.addMissionList(
            {
                "argd": {"phase": phase},
                "onGet": fail_callback if phase == "callback" else lambda *_args: None,
                "onEnd": lambda _info, message: (messages.append(message), failed.set()),
            },
            [{"value": "bad"}],
        )
        assert failed.wait(2), f"{phase} failure did not finish the waiting queue"
        assert len(messages) == 1 and messages[0].startswith("[Error]"), messages
        mission.addMissionList(
            {"argd": {}, "onEnd": lambda *_args: recovered.set()},
            [{"value": "good"}],
        )
        assert recovered.wait(2), f"worker did not recover after {phase} failure"

    mission = FailingMission()
    def fail_end(*_args):
        raise RuntimeError("forced end callback failure")
    mission.addMissionList({"argd": {}, "onEnd": fail_end}, [{"value": "first"}])
    recovered = threading.Event()
    mission.addMissionList(
        {"argd": {}, "onEnd": lambda *_args: recovered.set()}, [{"value": "second"}]
    )
    assert recovered.wait(2), "end callback failure blocked subsequent missions"


def test_end_callback_can_reenter_and_switch_configuration():
    class ReentrantMission(Mission):
        def msnPreTask(self, info):
            return "[Error] forced preparation result" if info.get("reject") else ""
        def msnTask(self, _info, _item):
            return {"code": 100, "data": "ok"}

    for reject in (False, True):
        mission = ReentrantMission()
        switched = threading.Event()
        observations = []
        def on_end(_info, _message):
            observations.append(mission.getMissionListsLength())
            switched.set()
        mission.addMissionList({"reject": reject, "onEnd": on_end}, [{"value": "item"}])
        assert switched.wait(2)
        assert observations == [{}], "ended queue still blocks reentrant configuration changes"


def test_configuration_barrier_and_cancel():
    class ControlledMission(Mission):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()
            self.seen = []
            self.configuration = "old"
        def msnTask(self, info, item):
            self.seen.append((item["value"], self.configuration))
            self.started.set()
            assert self.release.wait(5)
            return {"code":100,"data":item["value"]}
    mission=ControlledMission(); old_done=threading.Event(); new_done=threading.Event()
    old_id=mission.addMissionList({"onEnd":lambda *args:old_done.set()},[{"value":"old job"}])
    assert mission.started.wait(2)
    mission.deferAdmissions(True)
    new_id=mission.addMissionList({"onEnd":lambda *args:new_done.set()},[{"value":"new job"}])
    assert old_id in mission.getMissionListsLength() and new_id not in mission.getMissionListsLength()
    mission.release.set();assert old_done.wait(2)
    for _ in range(200):
        if not mission.getMissionListsLength():break
        import time;time.sleep(.01)
    assert not mission.getMissionListsLength()
    mission.configuration="new";mission.deferAdmissions(False)
    assert new_done.wait(2)
    assert mission.seen == [("old job","old"),("new job","new")]
    mission.deferAdmissions(True); cancelled=[]
    cancelled_id=mission.addMissionList({"onEnd":lambda *args:(mission.getMissionListsLength(),cancelled.append(args[-1]))},[{"value":"cancelled"}])
    mission.stopMissionList(cancelled_id);mission.deferAdmissions(False)
    assert cancelled == ["[Warning] Task stop."]
    assert len(mission.seen)==2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--source-root", type=Path, help="Test current source with an existing dependency runtime")
    args = parser.parse_args()
    handles = configure_runtime(args.data_root.resolve())
    if args.source_root:
        source_root = args.source_root.resolve()
        sys.path[:0] = [str(source_root), str(source_root / "py_src" / "imports")]

    from py_src.mission.mission import Mission as MissionClass
    from py_src.utils import thread_pool as thread_pool_module

    Mission = MissionClass
    thread_pool = thread_pool_module
    test_immediate_wait_has_no_lost_wakeup()
    test_stop_finishes_waiting_queue()
    test_full_qt_pool_does_not_expand()
    test_admission_during_worker_finish_is_not_stranded()
    test_worker_exception_finishes_queue_and_recovers()
    test_end_callback_can_reenter_and_switch_configuration()
    test_configuration_barrier_and_cancel()
    # Queue-end events precede the runnable's final cleanup.  Keep Qt and DLL
    # handles alive until all runnables finish, including restarted workers.
    assert thread_pool.GlobalThreadPool.waitForDone(5000), "mission worker did not finish"
    del handles
    print("Mission runtime regression tests passed.")
