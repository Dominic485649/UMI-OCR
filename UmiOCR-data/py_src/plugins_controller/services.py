# ===================================================
# =============== 插件共享服务注册表 ===============
# ===================================================

"""插件级共享服务。

能力实例是短生命周期的：用户切换 OCR / document 后端时，宿主会重新创建
它们。模型服务则可能需要被多个能力安全复用，因此把它从 capability 里提到
插件级。本模块只保存惰性入口，不在插件发现阶段导入任何重量级实现。
"""

from threading import RLock

from umi_log import logger


def _to_python_value(value):
    """把 QML/Qt 动态值规范化为普通 Python 容器。

    QML 调用 ``QVariant`` 槽时，JavaScript object 在 PySide6 中可能以
    ``QJSValue`` 到达 Python。共享服务的配置边界只接受普通 dict/list；
    因此在注册表入口统一解包，避免每个插件重复处理 Qt 类型。
    """
    to_variant = getattr(value, "toVariant", None)
    if callable(to_variant):
        value = to_variant()
    if isinstance(value, dict):
        return {key: _to_python_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_python_value(item) for item in value]
    return value


def _service_args(value):
    value = _to_python_value(value)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"共享服务参数必须是对象/字典，实际为 {type(value).__name__}。")
    return value

class PluginServiceRegistry:
    def __init__(self):
        self._entries = {}
        self._lock = RLock()

    def reset(self):
        with self._lock:
            self.shutdownAll()
            self._entries.clear()

    def register(self, pluginId, serviceId, resolve, config=None, meta=None):
        if not callable(resolve):
            raise TypeError(f"服务 {pluginId}/{serviceId} 的 resolve 必须可调用。")
        key = (pluginId, serviceId)
        with self._lock:
            if key in self._entries:
                raise ValueError(f"服务重复声明：{pluginId}/{serviceId}。")
            self._entries[key] = {
                "resolve": resolve,
                "config": config or {},
                "meta": dict(meta or {}),
                "instance": None,
            }

    def unregisterPlugin(self, pluginId):
        with self._lock:
            entries = [self._entries.pop(key) for key in list(self._entries) if key[0] == pluginId]
        for entry in entries:
            self._shutdown(entry.get("instance"))

    def has(self, pluginId, serviceId):
        with self._lock:
            return (pluginId, serviceId) in self._entries

    def get(self, pluginId, serviceId):
        # Health checks, prestart and inference can request the same lazy
        # service concurrently.  Publish one instance after resolution, and
        # leave it unset if resolution fails so the next request can retry.
        with self._lock:
            entry = self._entries.get((pluginId, serviceId))
            if not entry:
                raise KeyError(f'插件 "{pluginId}" 未声明共享服务 "{serviceId}"。')
            if entry["instance"] is None:
                entry["instance"] = entry["resolve"]()
            return entry["instance"]

    def configure(self, pluginId, serviceId, argd):
        service = self.get(pluginId, serviceId)
        method = getattr(service, "configure", None)
        if callable(method):
            return method(_service_args(argd))
        return {"ok": True, "message": "服务不需要额外配置。", "details": {}}

    def call(self, pluginId, serviceId, methodName, argd=None):
        try:
            if argd is not None:
                argd = _service_args(argd)
            service = self.get(pluginId, serviceId)
            method = getattr(service, methodName, None)
            if not callable(method):
                return {
                    "ok": False,
                    "message": f"共享服务不支持 {methodName}。",
                    "details": {},
                }
            if argd is None:
                result = method()
            else:
                configured = self.configure(pluginId, serviceId, argd)
                # configure() is allowed to reject a restart-causing change
                # while an OCR/document request owns a lease.  Do not ignore
                # that failure and then invoke the service with stale state.
                if isinstance(configured, dict) and not configured.get("ok", True):
                    return configured
                result = method(_service_args(argd))
            if isinstance(result, dict):
                return result
            return {"ok": True, "message": str(result or ""), "details": {}}
        except Exception as exc:
            logger.error(
                f"调用插件共享服务 {pluginId}/{serviceId}/{methodName} 失败。",
                exc_info=True,
            )
            return {"ok": False, "message": f"服务调用失败：{exc}", "details": {}}

    def status(self, pluginId, serviceId):
        try:
            service = self.get(pluginId, serviceId)
            method = getattr(service, "get_status", None)
            return method() if callable(method) else {}
        except Exception as exc:
            return {"state": "failed", "error": str(exc)}

    def options(self):
        result = {}
        with self._lock:
            for (pluginId, serviceId), entry in self._entries.items():
                result.setdefault(pluginId, []).append(
                    {
                        "id": serviceId,
                        "config": entry["config"],
                        "meta": dict(entry["meta"]),
                    }
                )
        return result

    def shutdownAll(self):
        with self._lock:
            for entry in tuple(self._entries.values()):
                self._shutdown(entry.get("instance"))

    @staticmethod
    def _shutdown(instance):
        method = getattr(instance, "shutdown_owned", None) if instance else None
        if callable(method):
            try:
                method()
            except Exception:
                logger.error("关闭插件共享服务失败。", exc_info=True)


PluginServices = PluginServiceRegistry()
