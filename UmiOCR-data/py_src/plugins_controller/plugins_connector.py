# =============================================
# =============== 插件管理连接器 ===============
# =============================================

from PySide6.QtCore import QObject, Slot, Signal

from .plugins_controller import PluginsController


# 插件连接器
class PluginsConnector(QObject):
    operationFinished = Signal(str, "QVariant")
    _pending = 0

    @Slot(result=bool)
    def isBusy(self):
        return self._pending > 0

    @Slot(str, str, str, "QVariant")
    def requestOperation(self, operation, pluginId, serviceId, argd):
        from ..utils.thread_pool import threadRun
        from .services import PluginServices, _to_python_value
        values = _to_python_value(argd)
        self._pending += 1
        def run():
            try:
                if operation == "shutdownServices":
                    PluginServices.shutdownAll()
                    result = {"ok": True, "message": "模型服务已释放", "details": {}}
                else:
                    result = (PluginsController.runHealthCheck(pluginId) if operation == "pluginHealth"
                          else PluginServices.call(pluginId, serviceId, operation, values))
            except Exception as exc:
                result = {"ok": False, "message": str(exc), "details": {}}
            finally:
                self._pending -= 1
            self.operationFinished.emit(operation + ":" + pluginId + ":" + serviceId, result)
        threadRun(run)

    @Slot(str)
    def releaseUnusedServices(self, activeOcr):
        from .services import PluginServices
        for (pluginId, serviceId), entry in list(PluginServices._entries.items()):
            service = entry.get("instance")
            if not service or pluginId == activeOcr:
                continue
            config = getattr(service, "_config", {})
            if config.get("lifecycle.prestartMode", "lazy") != "lazy":
                continue
            status = service.get_status()
            if status.get("state") != "busy":
                method = getattr(service, "stop_owned", None)
                if callable(method): self.requestOperation("stop_owned", pluginId, serviceId, None)

    # 初始化插件，返回字典：
    # {
    #   "options": {能力类型: {插件id: {global_options, local_options}}},
    #   "errors": {插件id: 失败原因},
    #   "pages": [插件页信息],
    #   "plugins": [每个插件的完整状态],
    #   "host": 宿主环境摘要,
    #   "capabilityTypes": [宿主支持的能力类型],
    # }
    @Slot(result="QVariant")
    def init(self):
        return PluginsController.init()

    # 全部插件的状态列表，供插件管理界面刷新
    @Slot(result="QVariant")
    def getPlugins(self):
        return PluginsController.getPlugins()

    # 启用/禁用一个插件。返回 [Success] 或 [Error] 开头的提示文本
    @Slot(str, bool, result=str)
    def setEnabled(self, pluginId, enabled):
        return PluginsController.setEnabled(pluginId, enabled)

    # 按需执行插件自带的健康检查，返回 {"ok", "message", "details"}
    @Slot(str, result="QVariant")
    def runHealthCheck(self, pluginId):
        return PluginsController.runHealthCheck(pluginId)

    # 宿主环境摘要（宿主 API 版本、平台、架构、Python 版本）
    @Slot(result="QVariant")
    def hostInfo(self):
        return PluginsController.hostInfo()

    @Slot(str, str, "QVariant", result="QVariant")
    def runServiceHealth(self, pluginId, serviceId, argd):
        from .services import PluginServices

        return PluginServices.call(pluginId, serviceId, "health", argd)

    @Slot(str, str, "QVariant", result="QVariant")
    def prestartService(self, pluginId, serviceId, argd):
        from .services import PluginServices

        return PluginServices.call(pluginId, serviceId, "prestart", argd)

    @Slot(str, str, "QVariant", result="QVariant")
    def maintainService(self, pluginId, serviceId, argd):
        from .services import PluginServices

        return PluginServices.call(pluginId, serviceId, "maintain", argd)

    @Slot(str, str, result="QVariant")
    def getServiceStatus(self, pluginId, serviceId):
        from .services import PluginServices

        return PluginServices.status(pluginId, serviceId)
