"""GUI/HTTP 模型任务的共享接纳、取消和资源保护。"""
from ..utils.runtime_i18n import tr
from contextlib import contextmanager, nullcontext

from umi_log import logger

from .mission import Mission
from .backend_runtime import BackendRuntime, BackendBusy, ManagedApi


class ManagedMission(Mission):
    _capability = ""

    def __init__(self, global_manager=False):
        super().__init__()
        self._global_manager = global_manager
        BackendRuntime.register_manager(self)

    @contextmanager
    def taskContext(self, info):
        api = getattr(self, "_api", None)
        method = getattr(api, "context", None)
        token = object()
        execution = (api, token)
        self._msnMutex.lock()
        try:
            info["_execution"] = execution
        finally:
            self._msnMutex.unlock()
        try:
            cancel = lambda: info.get("state") == "stop"
            context = (method(cancel, token=token) if isinstance(api, ManagedApi)
                       else method(cancel) if callable(method) else nullcontext())
            with context:
                yield
        finally:
            self._msnMutex.lock()
            try:
                if info.get("_execution") is execution:
                    info.pop("_execution", None)
            finally:
                self._msnMutex.unlock()

    def _enqueueMissionLocked(self, info, items):
        if BackendRuntime.admissions_deferred():
            self._deferAdmissions = True
        return super()._enqueueMissionLocked(info, items)

    def _reserveMission(self, info):
        try:
            BackendRuntime.reserve(info["msnID"], getattr(self, "_apiKey", ""))
        except BackendBusy as exc:
            return f"[Error] {exc}"
        return ""

    def _callMissionEnd(self, info, message):
        # 先归还队列容量，允许 onEnd 重入；独立收尾屏障禁止此时改配置。
        with BackendRuntime.finishing():
            BackendRuntime.unreserve(info.get("msnID") or info.get("_reserved_msnID"))
            try:
                super()._callMissionEnd(info, message)
            finally:
                if (not self._global_manager and not getattr(self, "_retain_runtime", False)
                        and not Mission.getMissionListsLength(self)):
                    api = getattr(self, "_api", None)
                    if api:
                        api.stop()

    def getMissionListsLength(self):
        result = Mission.getMissionListsLength(self)
        if self._global_manager:
            for manager in BackendRuntime.managers():
                if manager is not self and manager._capability == self._capability:
                    result.update(Mission.getMissionListsLength(manager))
        return result

    def backendsBusy(self):
        return BackendRuntime.configuration_busy()

    def configureBackends(self, values):
        return BackendRuntime.publish(values)

    def _cancelExecutions(self, executions):
        for api, token in executions:
            cancel = getattr(api, "cancel", None)
            if callable(cancel):
                try:
                    if isinstance(api, ManagedApi):
                        cancel(token)
                    else:
                        cancel()
                except Exception:
                    # 停止状态已经写入；取消失败不能丢失队列的结束通知。
                    logger.error(tr('取消模型任务失败。'), exc_info=True)

    def stopAllMissions(self):
        if self._global_manager:
            for manager in BackendRuntime.managers():
                if manager is not self and manager._capability == self._capability:
                    manager.stopAllMissions()
        return super().stopAllMissions()
