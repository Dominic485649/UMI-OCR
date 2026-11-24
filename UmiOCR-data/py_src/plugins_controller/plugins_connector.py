from ..utils.runtime_i18n import tr
# =============================================
# =============== 插件管理连接器 ===============
# =============================================

from PySide6.QtCore import QObject, Slot, Signal

# 插件连接器
class PluginsConnector(QObject):
    operationFinished = Signal(str, "QVariant")
    cudaDevicesDiscovered = Signal(str, "QVariant")
    _pending = 0
    modelDownloadChanged = Signal(str, "QVariant")

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QCoreApplication
        from ..utils.thread_pool import threadRun
        from .model_downloads import DownloadManager
        self._downloads = DownloadManager(self._modelResources, self.modelDownloadChanged.emit, threadRun)
        app = QCoreApplication.instance()
        if app:
            app.aboutToQuit.connect(self._downloads.close)

    @staticmethod
    def _modelResources(pluginId):
        from .plugins_controller import PluginsController, STATE_READY, STATE_UNHEALTHY
        record = PluginsController.records.get(pluginId)
        if not record or not record.manifest or record.state not in (STATE_READY, STATE_UNHEALTHY):
            raise ValueError(tr('当前插件未加载，不能确定模型安装目录。'))
        return record.path, record.manifest.modelDownloads

    @Slot(str, str, result="QVariant")
    def modelDownloadInfo(self, pluginId, resourceId):
        try:
            _root, _spec, info = self._downloads.info(pluginId, resourceId)
            return {"ok": True, **info}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    @Slot(str, str, str)
    def startModelDownload(self, requestId, pluginId, resourceId):
        self._downloads.start(requestId, pluginId, resourceId)

    @Slot(str)
    def cancelModelDownload(self, requestId):
        self._downloads.cancel(requestId)

    @Slot(str, bool)
    def discoverCudaDevices(self, requestId, force):
        def failure():
            return {"ok": False, "state": "failed", "devices": [],
                    "message": tr('NVIDIA 设备发现失败，请重试。')}

        def run():
            try:
                from ..utils.cuda_device_probe import discover_cuda_devices
                result = discover_cuda_devices(force=force)
            except Exception:
                result = failure()
            self.cudaDevicesDiscovered.emit(requestId, result)

        # 与插件操作及模型服务完全分离，不占用 _pending，也不在 UI 线程探测。
        try:
            from ..utils.thread_pool import threadRun
            threadRun(run)
        except Exception:
            self.cudaDevicesDiscovered.emit(requestId, failure())

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
                if operation in {"shutdownServices", "pluginHealth"}:
                    from ..mission.backend_runtime import BackendRuntime
                    with BackendRuntime.operation(pluginId or "shutdown", idle_only=True,
                                                  activate=operation == "pluginHealth"):
                        if operation == "shutdownServices":
                            PluginServices.shutdownAll()
                            result = {"ok": True, "message": tr('模型服务已释放'), "details": {}}
                        else:
                            from .plugins_controller import PluginsController
                            result = PluginsController.runHealthCheck(pluginId)
                else:
                    result = PluginServices.call(pluginId, serviceId, operation, values)
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
        from .plugins_controller import PluginsController
        return PluginsController.init()

    # 全部插件的状态列表，供插件管理界面刷新
    @Slot(result="QVariant")
    def getPlugins(self):
        from .plugins_controller import PluginsController
        return PluginsController.getPlugins()

    # 启用/禁用一个插件。返回 [Success] 或 [Error] 开头的提示文本
    @Slot(str, bool, result=str)
    def setEnabled(self, pluginId, enabled):
        from .plugins_controller import PluginsController
        return PluginsController.setEnabled(pluginId, enabled)

    # 按需执行插件自带的健康检查，返回 {"ok", "message", "details"}
    @Slot(str, result="QVariant")
    def runHealthCheck(self, pluginId):
        from .plugins_controller import PluginsController
        return PluginsController.runHealthCheck(pluginId)

    # 宿主环境摘要（宿主 API 版本、平台、架构、Python 版本）
    @Slot(result="QVariant")
    def hostInfo(self):
        from .plugins_controller import PluginsController
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
