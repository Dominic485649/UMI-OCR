"""统一重型模型执行许可和惰性后端复用。

GUI 与 HTTP 的 Mission 只持有轻量句柄。同一能力/插件最多一个真实 API，
跨后端切换先释放前一个后端，避免在小显存设备重复驻留模型。
"""
from __future__ import annotations
from ..utils.runtime_i18n import tr

from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
import json
import threading
import time
import weakref


def flatten_options(node, prefix=""):
    """只整理真实配置字段，不把分组标题或按钮当作参数。"""
    result = {}
    for key, definition in node.items():
        if not isinstance(definition, dict):
            continue
        full_key = prefix + key
        if definition.get("type") == "group":
            result.update(flatten_options(definition, full_key + "."))
        elif "default" in definition or "optionsList" in definition:
            result[full_key] = deepcopy(definition)
    return result


class BackendBusy(RuntimeError):
    pass


class BackendCancelled(RuntimeError):
    pass


@dataclass
class _Entry:
    factory: object
    instance: object = None
    fingerprint: str = ""
    loaded: bool = False
    last_used: float = 0.0
    start_fingerprint: str = ""
    handles: weakref.WeakSet = field(default_factory=weakref.WeakSet)


class RuntimeCoordinator:
    """许可覆盖初始化与推理，等待可取消，清理不越过活跃许可。"""

    def __init__(self, max_waiters=64):
        self._condition = threading.Condition(threading.RLock())
        self._queue = deque()
        self._thread = None
        self._depth = 0
        self._owner = None
        self._resident = None
        self._entries = {}
        self._configs = {}
        self._generation = 0
        self._max_waiters = max_waiters
        self._reservations = {}
        self._managers = weakref.WeakSet()

    def register_manager(self, manager):
        with self._condition:
            self._managers.add(manager)

    def managers(self):
        with self._condition:
            return tuple(self._managers)

    def configure(self, capability, backend_id, values):
        with self._condition:
            self._configs[(capability, backend_id)] = deepcopy(values)

    def configuration(self, capability, backend_id):
        with self._condition:
            return deepcopy(self._configs.get((capability, backend_id), {}))

    def publish(self, values):
        from ..plugins_controller.capabilities import CAPABILITY_TYPES
        from ..plugins_controller.services import PluginServices, _to_python_value
        values = _to_python_value(values)
        if not isinstance(values, dict):
            raise TypeError(tr('后端配置快照必须为字典。'))
        for capability, registry in CAPABILITY_TYPES.items():
            for backend_id in registry.keys():
                config = {}
                for key, definition in flatten_options(registry.globalOptions(backend_id) or {}).items():
                    config[key] = deepcopy(values.get(f"{capability}.{backend_id}.{key}", definition.get("default")))
                for service in PluginServices.options().get(backend_id, []):
                    for key, definition in flatten_options(service["config"]).items():
                        full = f"pluginServices.{backend_id}.{service['id']}.{key}"
                        config[key] = deepcopy(values.get(full, definition.get("default")))
                self.configure(capability, backend_id, config)
        return tr('[Success] 后端配置快照已同步。')

    def reserve(self, key, backend_id):
        with self._condition:
            if len(self._reservations) >= self._max_waiters:
                raise BackendBusy(tr('模型任务队列已满，请等待已有任务完成。'))
            self._reservations[key] = backend_id

    def unreserve(self, key):
        with self._condition:
            self._reservations.pop(key, None)
            self._condition.notify_all()
        self._close_unused(suppress_errors=True)

    def busy(self, owner=None):
        with self._condition:
            return bool(self._thread is not None or self._queue or self._reservations)

    def status(self):
        with self._condition:
            return {"activeBackend": self._owner or "", "waitingRequests": len(self._queue),
                    "pendingTasks": len(self._reservations)}

    @contextmanager
    def operation(self, owner, cancel=None, *, idle_only=False, warmup=False, activate=True):
        thread = threading.get_ident()
        ticket = object()
        nested = False
        with self._condition:
            if self._thread == thread:
                if self._owner != owner:
                    raise BackendBusy(tr('同一执行任务不能嵌套使用不同模型。'))
                self._depth += 1
                nested = True
            else:
                if idle_only and self.busy():
                    raise BackendBusy(tr('模型任务正在运行或排队，不能清理或重新配置。'))
                if warmup and self.busy():
                    raise BackendBusy(tr('已有模型任务，延后预热。'))
                if len(self._queue) >= self._max_waiters:
                    raise BackendBusy(tr('模型执行等待队列已满。'))
                self._queue.append(ticket)
                try:
                    while self._thread is not None or self._queue[0] is not ticket:
                        if cancel and cancel():
                            raise BackendCancelled(tr('任务已取消。'))
                        self._condition.wait(0.1)
                    if cancel and cancel():
                        raise BackendCancelled(tr('任务已取消。'))
                    self._queue.popleft()
                    self._thread, self._owner, self._depth = thread, owner, 1
                except BaseException:
                    if ticket in self._queue:
                        self._queue.remove(ticket)
                    self._condition.notify_all()
                    raise
        try:
            if not nested and activate:
                self._switch_resident(owner)
            yield
        finally:
            with self._condition:
                self._depth -= 1
                if not self._depth:
                    self._thread = None
                    self._owner = None
                    self._condition.notify_all()
            if not nested and activate:
                self._close_unused(suppress_errors=True)

    def _close_unused(self, *, suppress_errors=False):
        """最后一个句柄关闭后做最终 stop；忙时留到许可/预约退出再收尾。"""
        with self._condition:
            if self.busy():
                return
            owners = {owner for (_, owner), entry in self._entries.items()
                      if entry.instance is not None and not entry.handles}
        for owner in owners:
            try:
                with self.operation(owner, idle_only=True, activate=False):
                    with self._condition:
                        entries = [entry for (_, backend), entry in self._entries.items()
                                   if backend == owner]
                        if any(entry.handles for entry in entries):
                            continue
                    # 执行许可已排除推理；不要持注册锁调用插件，避免回调与接纳锁倒置。
                    for entry in entries:
                        instance = entry.instance
                        if instance is None:
                            continue
                        result = instance.stop()
                        if isinstance(result, str) and result.startswith("[Error]"):
                            raise RuntimeError(result)
                        with self._condition:
                            if entry.instance is instance:
                                entry.instance = None
                                entry.loaded = False
                                entry.fingerprint = entry.start_fingerprint = ""
                    errors = self._release_services(owner)
                    if errors:
                        raise RuntimeError("; ".join(errors))
                    if self._resident == owner:
                        self._resident = None
            except BackendBusy:
                # 有新任务预约/取得许可，绝不清理其资源。
                pass
            except Exception:
                if not suppress_errors:
                    raise

    def _switch_resident(self, owner):
        previous = self._resident
        if previous and previous != owner:
            self._release_owner(previous)
        self._resident = owner

    def _release_owner(self, owner):
        errors = []
        for (capability, backend_id), entry in tuple(self._entries.items()):
            if backend_id != owner or entry.instance is None:
                continue
            try:
                result = entry.instance.release()
                if isinstance(result, str) and result.startswith("[Error]"):
                    errors.append(result)
                else:
                    entry.loaded = False
            except Exception as exc:
                errors.append(str(exc))
        errors.extend(self._release_services(owner))
        if errors:
            raise BackendBusy(tr('上一模型尚未安全释放：{items}', items='; '.join(errors)))

    def _release_services(self, owner):
        errors = []
        try:
            from ..plugins_controller.services import PluginServices
        except ImportError:
            PluginServices = None
        if PluginServices is not None:
            for (plugin_id, _), service_entry in tuple(PluginServices._entries.items()):
                service = service_entry.get("instance")
                if plugin_id != owner or service is None:
                    continue
                try:
                    stop = getattr(service, "stop_owned", None) or getattr(service, "shutdown_owned", None)
                    if callable(stop):
                        result = stop()
                        if isinstance(result, dict) and not result.get("ok", True):
                            errors.append(str(result.get("message", tr('共享服务尚未释放'))))
                        elif isinstance(result, str) and result.startswith("[Error]"):
                            errors.append(result)
                except Exception as exc:
                    errors.append(str(exc))
        return errors

    def handle(self, capability, backend_id, config, factory):
        key = (capability, backend_id)
        with self._condition:
            entry = self._entries.get(key)
            if entry is None:
                entry = self._entries[key] = _Entry(factory=factory)
            handle = ManagedApi(self, key, deepcopy(config), self._generation)
            entry.handles.add(handle)
            return handle

    def _instance(self, handle):
        if handle.generation != self._generation:
            raise BackendBusy(tr('插件配置已刷新，请重新提交任务。'))
        entry = self._entries[handle.key]
        fingerprint = json.dumps(handle.config, sort_keys=True, ensure_ascii=False, default=str)
        if entry.instance is None or entry.fingerprint != fingerprint:
            if entry.instance is not None:
                entry.instance.stop()
            instance = entry.factory(handle.key[1], deepcopy(handle.config))
            if isinstance(instance, str):
                raise RuntimeError(instance)
            entry.instance, entry.fingerprint, entry.loaded = instance, fingerprint, False
        return entry

    def reset(self):
        with self._condition:
            if self.busy():
                raise BackendBusy(tr('模型任务尚未完成，不能刷新插件。'))
            for entry in self._entries.values():
                if entry.instance is not None:
                    entry.instance.stop()
            self._entries.clear()
            self._configs.clear()
            self._resident = None
            self._generation += 1


class ManagedApi:
    def __init__(self, coordinator, key, config, generation):
        self.coordinator, self.key, self.config, self.generation = coordinator, key, config, generation
        self._start_info = None
        self._warmup_thread = None
        self.on_progress = None
        self.on_partial = None
        self._active_thread = None
        self._active_token = None
        self._active_depth = 0
        self._last_error = ""
        self._state_lock = threading.Lock()
        self._cancel_finished = threading.Event()
        self._cancel_finished.set()

    @contextmanager
    def context(self, cancel=None, *, token=None):
        with self.coordinator.operation(self.key[1], cancel):
            with self._state_lock:
                if not self._active_depth:
                    self._active_thread = threading.get_ident()
                    self._active_token = token
                self._active_depth += 1
            try:
                yield
            finally:
                with self._state_lock:
                    self._active_depth -= 1
                    outer = not self._active_depth
                    if outer:
                        self._active_thread = None
                        self._active_token = None
                # 取消方也可能仍在等待自有子进程退出，不能抢先交出执行许可。
                if outer:
                    self._cancel_finished.wait()

    def start(self, values):
        with self.context():
            entry = self.coordinator._instance(self)
            if hasattr(entry.instance, "on_progress") or self.on_progress:
                entry.instance.on_progress = self.on_progress
            if hasattr(entry.instance, "on_partial") or self.on_partial:
                entry.instance.on_partial = self.on_partial
            result = entry.instance.start(deepcopy(values))
            if not isinstance(result, str) or not result.startswith("[Error]"):
                self._start_info = deepcopy(values)
                entry.start_fingerprint = json.dumps(values, sort_keys=True, default=str)
                entry.loaded = True
            return result

    def _run(self, method, *args):
        with self.context():
            entry = self.coordinator._instance(self)
            if self._start_info is None:
                raise RuntimeError(tr('后端尚未启动。'))
            if (not entry.loaded or entry.start_fingerprint !=
                    json.dumps(self._start_info, sort_keys=True, default=str)):
                result = self.start(self._start_info)
                if isinstance(result, str) and result.startswith("[Error]"):
                    raise RuntimeError(result)
            try:
                return getattr(entry.instance, method)(*args)
            finally:
                entry.last_used = time.monotonic()

    def runPath(self, value):
        return self._run("runPath", value)

    def runBytes(self, value):
        return self._run("runBytes", value)

    def runBase64(self, value):
        return self._run("runBase64", value)

    def parseDoc(self, value):
        return self._run("parseDoc", value)

    def get_execution_info(self):
        entry = self.coordinator._entries.get(self.key)
        method = getattr(entry.instance, "get_execution_info", None) if entry else None
        return method() if callable(method) else {"model": self.key[1], "device": tr('设备未确认')}

    def get_status(self):
        entry = self.coordinator._entries.get(self.key)
        if entry and entry.instance is not None:
            result = dict(entry.instance.get_status())
        else:
            result = {"state": "unloaded", "idleSeconds": 0, "error": ""}
        if self._warmup_thread and self._warmup_thread.is_alive():
            result["state"] = "warming"
        if self._last_error:
            result["error"] = self._last_error
        return result

    def warmup(self, values):
        if self._warmup_thread and self._warmup_thread.is_alive():
            return tr('[Success] 模型正在后台预热。')
        def run():
            try:
                with self.coordinator.operation(self.key[1], warmup=True):
                    self._last_error = self.start(values) or ""
            except BackendBusy:
                pass
            except Exception as exc:
                self._last_error = str(exc)
        self._warmup_thread = threading.Thread(target=run, name="UmiOCR-ManagedWarmup", daemon=True)
        self._warmup_thread.start()
        return tr('[Success] 模型预热已安排。')

    def release(self):
        try:
            with self.coordinator.operation(self.key[1], idle_only=True, activate=False):
                self.coordinator._release_owner(self.key[1])
            return tr('[Success] 模型后台已清理。')
        except BackendBusy as exc:
            return f"[Error] {exc}"

    def stop(self):
        with self.coordinator._condition:
            entry = self.coordinator._entries.get(self.key)
            if entry:
                entry.handles.discard(self)
        self.coordinator._close_unused()

    def cancel(self, token=None):
        # 只有正在执行本句柄的 Mission 才可调用，排队取消不终止其他任务。
        with self._state_lock:
            if (self._active_thread is None or not self._cancel_finished.is_set()
                    or (token is not None and self._active_token is not token)):
                return
            self._cancel_finished.clear()
        try:
            entry = self.coordinator._entries.get(self.key)
            method = getattr(entry.instance, "cancel", None) if entry else None
            if callable(method):
                method()
        finally:
            self._cancel_finished.set()

    def health(self, values):
        with self.context():
            entry = self.coordinator._instance(self)
            return entry.instance.health(values)


BackendRuntime = RuntimeCoordinator()
